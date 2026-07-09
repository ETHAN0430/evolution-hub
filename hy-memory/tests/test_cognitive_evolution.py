import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from hy_memory.data.graph_relations import (
    COGNITIVE_EDGE_TYPES,
    MEMORY_EDGE_TYPES,
    RELATED_TO,
    infer_cognitive_edge_type_from_reason,
    normalize_memory_edge_type,
    plan_legacy_related_direction,
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
from hy_memory.pipelines.system2_writer import build_digest_quality_report


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


class FakeEmbedService:
    async def embed_queued(self, text):
        return [1.0, 0.0, 0.0]


class FakeVectorStore:
    def __init__(self):
        self.updated = []

    async def get_by_id(self, node_id):
        return SimpleNamespace(layer=SimpleNamespace(value="l2_fact"), custom={})

    async def update_payload(self, node_id, updates):
        self.updated.append((node_id, updates))


class FakeDuplicateGraphStore:
    def __init__(self):
        self.derived = []
        self.upserts = []

    async def vector_search(self, **kwargs):
        return [{"node_id": "existing-schema", "score": 0.981}]

    async def ensure_vdbref(self, evidence_id, layer):
        return True

    async def add_derived_from(self, node_id, evidence_id):
        self.derived.append((node_id, evidence_id))
        return True

    async def upsert_memory_node(self, node):
        self.upserts.append(node)

    async def add_topic_tag(self, *args, **kwargs):
        return "tag"


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
        self.assertEqual(
            infer_cognitive_edge_type_from_reason("广告归因经验导致防御绕过框架形成"),
            "LED_TO",
        )
        self.assertEqual(
            infer_cognitive_edge_type_from_reason("新证据反驳了旧观点"),
            "CONTRADICTED_BY",
        )
        self.assertEqual(
            infer_cognitive_edge_type_from_reason("该框架受到广告归因证据支持"),
            "SUPPORTED_BY",
        )
        self.assertEqual(
            infer_cognitive_edge_type_from_reason("两个 Schema 主题相近"),
            RELATED_TO,
        )

    def test_legacy_related_direction_is_conservative(self):
        old_time = datetime.now() - timedelta(days=1)
        new_time = datetime.now()
        led_to = plan_legacy_related_direction("LED_TO", "old", old_time, "new", new_time)
        corrected = plan_legacy_related_direction("CORRECTED", "old", old_time, "new", new_time)
        supported = plan_legacy_related_direction("SUPPORTED_BY", "old", old_time, "new", new_time)
        self.assertEqual((led_to["source"], led_to["target"]), ("old", "new"))
        self.assertEqual((corrected["source"], corrected["target"]), ("new", "old"))
        self.assertEqual(supported["status"], "ambiguous")

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

    def test_create_schema_reuses_high_similarity_existing_schema(self):
        executor = System2ToolExecutor(
            vector_store=FakeVectorStore(),
            graph_store=FakeDuplicateGraphStore(),
            embed_service=FakeEmbedService(),
            user_id="user",
            agent_id="agent",
        )
        result = asyncio.run(executor._tool_create_graph_node({
            "layer": "l6_schema",
            "content": "duplicate schema",
            "evidence_list": ["fact-1"],
            "tags": ["test"],
        }))
        self.assertFalse(result["created"])
        self.assertEqual(result["node_id"], "existing-schema")
        self.assertEqual(executor.graph_store.derived, [("existing-schema", "fact-1")])
        self.assertEqual(executor.graph_store.upserts, [])

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

    def test_legacy_related_migration_is_dry_run_first(self):
        store = KuzuGraphStore.__new__(KuzuGraphStore)
        store._available = True
        calls = []
        old_time = datetime.now() - timedelta(days=1)
        new_time = datetime.now()

        def execute(query, params=None):
            calls.append((query, params))
            if "RETURN a.node_id" in query:
                return FakeKuzuResult([
                    ["old", old_time, "new", new_time, "广告归因经验导致防御绕过框架形成", 0.9],
                    ["a", old_time, "b", new_time, "该框架受到广告归因证据支持", 0.7],
                    ["x", old_time, "y", new_time, "两个 Schema 主题相近", 0.5],
                ])
            return None

        store._execute = execute
        plan = asyncio.run(store.migrate_legacy_related_edges("user", dry_run=True))
        self.assertEqual(plan["migrate"][0]["edge_type"], "LED_TO")
        self.assertEqual((plan["migrate"][0]["source"], plan["migrate"][0]["target"]), ("old", "new"))
        self.assertEqual(plan["ambiguous"][0]["edge_type"], "SUPPORTED_BY")
        self.assertEqual(plan["skipped"], 1)

        async def fake_add_edge(source, target, edge_type, properties=None):
            calls.append(("add_edge", {"source": source, "target": target, "edge_type": edge_type}))
            return True

        store.add_edge = fake_add_edge
        applied = asyncio.run(store.migrate_legacy_related_edges("user", dry_run=False))
        self.assertEqual(applied["applied"], 1)

    def test_duplicate_schema_audit_groups_high_similarity_pairs(self):
        store = KuzuGraphStore.__new__(KuzuGraphStore)
        store._available = True
        now = datetime.now()

        def execute(query, params=None):
            if "RETURN m.node_id" in query:
                return FakeKuzuResult([
                    ["schema-a", "A", now, [1.0, 0.0]],
                    ["schema-b", "B", now, [0.99, 0.01]],
                    ["schema-c", "C", now, [0.0, 1.0]],
                ])
            return None

        store._execute = execute
        audit = asyncio.run(store.audit_duplicate_schema_nodes("user", threshold=0.95))
        self.assertEqual(len(audit["pairs"]), 1)
        self.assertEqual({n["node_id"] for n in audit["groups"][0]}, {"schema-a", "schema-b"})

    def test_graph_health_snapshot_counts_edges_and_orphans(self):
        store = KuzuGraphStore.__new__(KuzuGraphStore)
        store._available = True

        def execute(query, params=None):
            if "RETURN m.node_id" in query and "m.embedding" not in query:
                return FakeKuzuResult([["schema-a"], ["schema-b"], ["schema-c"]])
            if "[r:RELATED_TO]" in query:
                return FakeKuzuResult([["schema-a", "schema-b"], ["schema-b", "schema-a"]])
            if "[r:LED_TO]" in query:
                return FakeKuzuResult([["schema-b", "schema-c"]])
            return FakeKuzuResult([])

        async def fake_evidence(node_id):
            return [] if node_id == "schema-c" else [{"node_id": f"fact-{node_id}", "layer": "l2_fact"}]

        async def fake_audit(**kwargs):
            return {"pairs": [{"nodes": []}], "groups": [[{"node_id": "schema-a"}, {"node_id": "schema-b"}]]}

        store._execute = execute
        store.get_evidence_vdbrefs = fake_evidence
        store.audit_duplicate_schema_nodes = fake_audit

        health = asyncio.run(store.graph_health_snapshot("user"))
        self.assertEqual(health["schema_total"], 3)
        self.assertEqual(health["edge_type_counts"]["RELATED_TO"], 1)
        self.assertEqual(health["edge_type_counts"]["LED_TO"], 1)
        self.assertEqual(health["memory_edge_total"], 2)
        self.assertEqual(health["cognitive_edge_total"], 1)
        self.assertEqual(health["orphan_schema_count"], 0)
        self.assertEqual(health["no_evidence_schema_count"], 1)
        self.assertEqual(health["duplicate_groups"], 1)

    def test_digest_quality_report_counts_reuse_and_edge_types(self):
        results = {
            "system2_agent": {
                "tool_call_log": [
                    {
                        "tool": "create_graph_node",
                        "result": '{"node_id":"schema-1","created":true,"evidence_count":2}',
                    },
                    {
                        "tool": "create_graph_node",
                        "result": '{"node_id":"schema-1","created":false,"duplicate_of":"schema-1","evidence_count":1}',
                    },
                    {
                        "tool": "add_edge",
                        "args": {"edge_type": "RELATED_TO"},
                        "result": '{"success":true,"edge":"(a)-[:LED_TO]->(b)"}',
                    },
                    {
                        "tool": "add_edge",
                        "args": {"edge_type": "RELATED_TO"},
                        "result": '{"success":true,"edge":"(a)-[:RELATED_TO]->(b)"}',
                    },
                ]
            }
        }
        report = build_digest_quality_report(results, {"skipped": True})
        self.assertEqual(report["schema_created"], 1)
        self.assertEqual(report["schema_reused"], 1)
        self.assertEqual(report["evidence_added"], 3)
        self.assertEqual(report["edge_type_counts"]["LED_TO"], 1)
        self.assertEqual(report["related_to_ratio"], 0.5)
        self.assertIn("duplicate_schema_reused", report["warnings"])


if __name__ == "__main__":
    unittest.main()
