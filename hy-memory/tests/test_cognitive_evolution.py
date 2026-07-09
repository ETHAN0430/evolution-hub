import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from hy_memory.data.graph_relations import (
    COGNITIVE_EDGE_TYPES,
    MEMORY_EDGE_TYPES,
    RELATED_TO,
    normalize_memory_edge_type,
)
from hy_memory.data.graph_store_kuzu import KuzuGraphStore
from hy_memory.pipelines._retrieval.evolution import expand_evolution_chains
from hy_memory.pipelines.system2_agent import (
    SYSTEM2_AGENT_PROMPT_ZH,
    _build_materials_message,
    run_system2_agent,
    s2_agent_skip_reason,
)
from hy_memory.pipelines.system2_tools import System2ToolExecutor


class FakeGraphStore:
    async def get_cognitive_relations(self, node_ids, max_nodes=30):
        return [{
            "node_id": "evidence-1",
            "content": "A new observation contradicted the old belief.",
            "edge_type": "CONTRADICTED_BY",
            "direction": "outgoing",
            "from_anchor": node_ids[0],
            "weight": 0.9,
        }]


class FakeToolExecutor:
    def __init__(self):
        self.calls = []
        self.tool_call_log = []

    async def execute(self, name, args):
        self.calls.append((name, args))
        if name == "create_graph_node":
            return {"node_id": "generated-schema-id", "created": True}
        return {"success": True}


class FakeLLMProvider:
    def __init__(self, config):
        pass

    async def complete_messages(self, **kwargs):
        return SimpleNamespace(
            content='''```json
[
  {"op":"create_schema","ref":"belief_v2","content":"new belief","evidence_list":["fact-1"]},
  {"op":"add_edge","source_id":"$belief_v2","target_id":"old-schema","edge_type":"CORRECTED","reason":"new evidence"}
]
```''',
            prompt_tokens=10,
            completion_tokens=20,
        )


class FakeKuzuResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def has_next(self):
        return bool(self.rows)

    def get_next(self):
        return self.rows.pop(0)


class CognitiveRelationTests(unittest.TestCase):
    def test_relation_registry_contains_causal_edges(self):
        self.assertIn("SUPPORTED_BY", COGNITIVE_EDGE_TYPES)
        self.assertIn("CONTRADICTED_BY", COGNITIVE_EDGE_TYPES)
        self.assertIn("LED_TO", COGNITIVE_EDGE_TYPES)
        self.assertIn("RESULTED_IN", COGNITIVE_EDGE_TYPES)
        self.assertIn(RELATED_TO, MEMORY_EDGE_TYPES)

    def test_relation_normalization_is_safe(self):
        self.assertEqual(normalize_memory_edge_type("led_to"), "LED_TO")
        self.assertEqual(normalize_memory_edge_type("unknown"), RELATED_TO)

    def test_prompt_makes_related_to_last_resort(self):
        self.assertIn("不要因为主题相似就连边", SYSTEM2_AGENT_PROMPT_ZH)
        self.assertIn("RELATED_TO` — 最后兜底", SYSTEM2_AGENT_PROMPT_ZH)

    def test_related_to_reason_can_be_refined(self):
        executor = System2ToolExecutor.__new__(System2ToolExecutor)
        self.assertEqual(
            executor._refine_related_to_edge_type("广告归因经验导致防御绕过框架形成"),
            "LED_TO",
        )
        self.assertEqual(
            executor._refine_related_to_edge_type("新证据反驳了旧观点"),
            "CONTRADICTED_BY",
        )
        self.assertEqual(
            executor._refine_related_to_edge_type("该框架受到广告归因证据支持"),
            "SUPPORTED_BY",
        )
        self.assertEqual(
            executor._refine_related_to_edge_type("两个 Schema 主题相近"),
            RELATED_TO,
        )

    def test_non_chain_hit_gets_cognitive_relations(self):
        hits = [{"node_id": "belief-1", "content": "Current belief", "score": 0.8}]
        result = asyncio.run(
            expand_evolution_chains(object(), hits, FakeGraphStore())
        )
        self.assertEqual(result[0]["cognitive_relations"][0]["edge_type"], "CONTRADICTED_BY")
        self.assertEqual(result[0]["cognitive_relations"][0]["from_anchor"], "belief-1")

    def test_only_related_to_is_written_bidirectionally(self):
        store = KuzuGraphStore.__new__(KuzuGraphStore)
        store._available = True
        calls = []
        store._execute = lambda query, params=None: calls.append(query)

        self.assertTrue(asyncio.run(store.add_edge("a", "b", "LED_TO")))
        self.assertEqual(len(calls), 1)

        calls.clear()
        self.assertTrue(asyncio.run(store.add_edge("a", "b", RELATED_TO)))
        self.assertEqual(len(calls), 2)

    def test_scattered_fact_can_trigger_against_existing_schema(self):
        materials = {
            "stats": {"total_facts_pool": 1, "clusters_found": 0},
            "graph_forward": [{"node_id": "old-schema"}],
        }
        self.assertIsNone(s2_agent_skip_reason(materials))

    def test_scattered_evolution_fact_is_visible_to_agent(self):
        materials = {
            "clusters": [],
            "unprocessed_facts": [{"node_id": "fact-1", "content": "关键反例", "layer": "l2_fact"}],
            "graph_forward": [{
                "node_id": "old-schema", "content": "旧观点", "layer": "l6_schema",
                "evidence_count": 1,
            }],
            "graph_reverse": [],
            "existing_tags": [],
            "stats": {"total_facts_pool": 1, "clusters_found": 0, "graph_total_schemas": 1},
        }
        prompt = _build_materials_message(materials, lang="zh")
        self.assertIn("散事实演化候选", prompt)
        self.assertIn("关键反例", prompt)

    def test_same_response_schema_reference_is_resolved(self):
        executor = FakeToolExecutor()
        config = SimpleNamespace(
            llm=SimpleNamespace(agent_max_tokens=4000, temperature=0.0),
        )
        materials = {
            "clusters": [{
                "centroid_text": "belief",
                "facts": [{"node_id": "fact-1", "content": "new evidence", "layer": "l2_fact"}],
            }],
            "unprocessed_facts": [],
            "graph_forward": [{
                "node_id": "old-schema", "content": "old belief", "layer": "l6_schema",
                "evidence_count": 1,
            }],
            "graph_reverse": [],
            "existing_tags": [],
            "stats": {"total_facts_pool": 1, "clusters_found": 1, "graph_total_schemas": 1},
        }
        with patch("hy_memory.agent.llm_provider.LLMProvider", FakeLLMProvider):
            result = asyncio.run(run_system2_agent(materials, executor, config))
        self.assertTrue(result["success"])
        self.assertEqual(executor.calls[1][1]["source_id"], "generated-schema-id")

    def test_legacy_corrected_normalization_is_dry_run_first(self):
        store = KuzuGraphStore.__new__(KuzuGraphStore)
        store._available = True
        deleted = []
        old_time = datetime.now() - timedelta(days=1)
        new_time = datetime.now()

        def execute(query, params=None):
            if "RETURN a.node_id" in query:
                return FakeKuzuResult([["old", old_time, "new", new_time]])
            deleted.append(params)
            return None

        store._execute = execute
        plan = asyncio.run(store.normalize_legacy_cognitive_edges("user", dry_run=True))
        self.assertEqual(plan["corrected"][0]["keep"], ["new", "old"])
        self.assertEqual(deleted, [])

        applied = asyncio.run(store.normalize_legacy_cognitive_edges("user", dry_run=False))
        self.assertEqual(applied["applied"], 1)
        self.assertEqual(deleted[0], {"older": "old", "newer": "new"})


if __name__ == "__main__":
    unittest.main()
