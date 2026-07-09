"""
Agent Memory V2 - Neo4jGraphStore

基于 Neo4j 图数据库的图存储层实现。

使用 **同步** neo4j Python driver + asyncio.to_thread 包装为异步，
彻底避免 AsyncGraphDatabase.driver 的 event loop 绑定问题
（与 Qdrant 存储层同一策略）。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio
import concurrent.futures
import logging
import json

from ..models.memory import MemoryNode, MemoryLayer, MemoryStatus
from ..config import MemoryConfig
from .graph_store_base import GraphStoreBase
from .graph_relations import (
    COGNITIVE_EDGE_TYPES,
    MEMORY_EDGE_TYPES,
    RELATED_TO,
    cosine_similarity,
    infer_cognitive_edge_type_from_reason,
    plan_legacy_related_direction,
)

logger = logging.getLogger(__name__)

# Graph 独立线程池（不与 VDB/SQLite 竞争）
_GRAPH_POOL_SIZE = 64
_graph_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_GRAPH_POOL_SIZE, thread_name_prefix="graph"
)


def _run_in_graph_pool(func, *args, **kwargs):
    """在 Graph 独立线程池中执行同步函数"""
    import functools
    loop = asyncio.get_event_loop()
    if args or kwargs:
        return loop.run_in_executor(_graph_executor, functools.partial(func, *args, **kwargs))
    return loop.run_in_executor(_graph_executor, func)

# Neo4j Schema 初始化 Cypher (约束 + 索引)
_NEO4J_SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.isolation_key IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Memory) REQUIRE m.node_id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE",
    "CREATE INDEX IF NOT EXISTS FOR (m:Memory) ON (m.isolation_key)",
    "CREATE INDEX IF NOT EXISTS FOR (m:Memory) ON (m.layer)",
    "CREATE INDEX IF NOT EXISTS FOR (m:Memory) ON (m.status)",
    "CREATE INDEX IF NOT EXISTS FOR (m:Memory) ON (m.valid_from)",
    "CREATE INDEX IF NOT EXISTS FOR (t:Topic) ON (t.isolation_key)",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (v:VdbRef) REQUIRE v.node_id IS UNIQUE",
]


def _make_vector_index_statements(dims: int) -> List[str]:
    """生成向量索引 DDL（依赖 embedding_dims）"""
    return [
        # V_con 内容向量索引
        f"""CREATE VECTOR INDEX memory_content_idx IF NOT EXISTS
FOR (m:Memory) ON (m.embedding)
OPTIONS {{indexConfig: {{
    `vector.dimensions`: {dims},
    `vector.similarity_function`: 'cosine'
}}}}""",
        # V_beh 行为向量索引
        f"""CREATE VECTOR INDEX memory_behavior_idx IF NOT EXISTS
FOR (m:Memory) ON (m.beh_embedding)
OPTIONS {{indexConfig: {{
    `vector.dimensions`: {dims},
    `vector.similarity_function`: 'cosine'
}}}}""",
    ]


class Neo4jGraphStore(GraphStoreBase):
    """
    Neo4j 图存储（推荐后端）

    使用 **同步** neo4j GraphDatabase.driver + asyncio.to_thread，
    彻底绕开 AsyncGraphDatabase event loop 绑定问题。
    """

    def __init__(self, config: MemoryConfig):
        super().__init__(config)
        self._driver = None  # 同步 driver

        # embedding 维度
        vs_dims = getattr(getattr(config, 'vector_store', None), 'embedding_dims', None)
        emb_dims = getattr(getattr(config, 'embedder', None), 'embedding_dims', None)
        self._embedding_dims = vs_dims or emb_dims or 1536

        graph_config = getattr(config, 'graph_store', None)
        self._url = getattr(graph_config, 'url', None) or "bolt://localhost:7687"
        self._username = getattr(graph_config, 'username', None) or "neo4j"
        self._password = getattr(graph_config, 'password', None) or "neo4j"
        self._database = getattr(graph_config, 'database', None) or "neo4j"

    async def initialize(self) -> None:
        """初始化 Neo4j 连接并创建 Schema + 双向量索引"""
        try:
            import neo4j
        except ImportError:
            raise ImportError(
                "neo4j is required. Install with: pip install neo4j"
            )

        import os as _os
        _neo4j_pool_size = int(_os.environ.get("NEO4J_POOL_SIZE", "256"))
        self._driver = neo4j.GraphDatabase.driver(
            self._url,
            auth=(self._username, self._password),
            max_connection_pool_size=_neo4j_pool_size,
            connection_acquisition_timeout=120,
        )
        logger.info(f"[neo4j] pool_size={_neo4j_pool_size}")
        # 验证连接
        await _run_in_graph_pool(self._driver.verify_connectivity)

        # 创建约束和索引
        def _init_schema():
            with self._driver.session(database=self._database) as session:
                for stmt in _NEO4J_SCHEMA_STATEMENTS:
                    try:
                        session.run(stmt).consume()
                    except Exception as e:
                        logger.debug(f"Neo4j schema DDL note: {e}")

                # 创建双向量 HNSW 索引
                dims = self._embedding_dims
                for stmt in _make_vector_index_statements(dims):
                    try:
                        session.run(stmt).consume()
                    except Exception as e:
                        logger.debug(f"Neo4j vector index DDL note: {e}")

        await _run_in_graph_pool(_init_schema)

        logger.info(
            f"Neo4jGraphStore initialized (sync driver), url={self._url}, "
            f"database={self._database}, embedding_dims={self._embedding_dims}"
        )

    async def _run(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """执行 Cypher 查询并返回结果列表 (每行是一个 dict)"""
        if self._driver is None:
            return []
        def _exec():
            with self._driver.session(database=self._database) as session:
                result = session.run(query, params or {})
                return result.data()
        return await _run_in_graph_pool(_exec)

    async def _run_single(self, query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """执行查询并返回第一行 (或 None)"""
        rows = await self._run(query, params)
        return rows[0] if rows else None

    async def _run_write(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        """执行写入操作"""
        if self._driver is None:
            return
        def _exec():
            with self._driver.session(database=self._database) as session:
                session.run(query, params or {}).consume()
        await _run_in_graph_pool(_exec)

    # ================================================================
    # 生命周期
    # ================================================================

    async def close(self) -> None:
        """关闭连接"""
        if self._driver:
            self._driver.close()
            self._driver = None
        logger.info("Neo4jGraphStore closed")

    async def get_stats(self) -> Dict[str, Any]:
        """获取图统计"""
        try:
            mc = await self._run_single("MATCH (m:Memory) RETURN count(m) AS cnt")
            uc = await self._run_single("MATCH (u:User) RETURN count(u) AS cnt")
            return {
                "backend": "neo4j",
                "url": self._url,
                "database": self._database,
                "memory_nodes": mc["cnt"] if mc else 0,
                "user_nodes": uc["cnt"] if uc else 0,
            }
        except Exception as e:
            return {"backend": "neo4j", "error": str(e)}

    # ================================================================
    # User 节点管理
    # ================================================================

    async def ensure_user_node(self, isolation_key: str, user_id: str = "",
                                agent_id: str = "") -> None:
        """确保 User 节点存在"""
        try:
            await self._run_write(
                "MERGE (u:User {isolation_key: $ik}) "
                "ON CREATE SET u.user_id = $uid, "
                "u.agent_id = $sid, u.created_at = datetime()",
                {"ik": isolation_key, "uid": user_id, "sid": agent_id},
            )
        except Exception as e:
            logger.warning(f"ensure_user_node failed: {e}")

    # ================================================================
    # Memory 节点 CRUD
    # ================================================================

    async def upsert_memory_node(self, node: MemoryNode) -> str:
        """创建或更新 Memory 节点 + User→Memory 边"""
        isolation_key = node.get_isolation_key()
        await self.ensure_user_node(
            isolation_key, node.user_id, node.agent_id
        )

        now = datetime.now().isoformat()

        params = {
            "nid": node.node_id,
            "ik": isolation_key,
            "uid": node.user_id,
            "sid": node.agent_id,
            "layer": node.layer.value,
            "content": node.content,
            "status": node.status.value,
            "ver": getattr(node, 'version', 1) or 1,
            "conf": node.confidence,
            "ac": getattr(node, 'access_count', 0) or 0,
            "cat": (getattr(node, 'created_at', None) or datetime.now()).isoformat(),
            "vf": (node.valid_from or datetime.now()).isoformat(),
            "vu": node.valid_until.isoformat() if node.valid_until else None,
            "laat": getattr(node, 'last_accessed_at', None),
            "sbid": getattr(node, 'superseded_by_id', '') or '',
            "ec": json.dumps(getattr(node, 'evidence_chain', []) or []),
            "cust": json.dumps(getattr(node, 'custom', {}) or {}),
            "tags": json.dumps(getattr(node, 'tags', []) or []),
            "extra": "{}",
            "now": now,
            "emb": getattr(node, '_graph_embedding', None) or getattr(node, 'embedding', None),
        }

        # embedding SET 子句（仅在有值时写入，避免覆盖已有 embedding 为 NULL）
        emb_set_create = ", m.embedding = $emb" if params["emb"] else ""
        emb_set_match = ", m.embedding = $emb" if params["emb"] else ""

        # MERGE 保证幂等
        await self._run_write(
            f"""
            MERGE (m:Memory {{node_id: $nid}})
            ON CREATE SET
                m.isolation_key = $ik, m.user_id = $uid,
                m.agent_id = $sid, m.layer = $layer, m.content = $content,
                m.status = $status, m.version = $ver,
                m.confidence = $conf,
                m.access_count = $ac,
                m.created_at = $cat, m.valid_from = $vf, m.valid_until = $vu,
                m.last_accessed_at = $laat,
                m.superseded_by_id = $sbid,
                m.evidence_chain = $ec,
                m.custom_json = $cust, m.tags = $tags, m.extra_json = $extra
                {emb_set_create}
            ON MATCH SET
                m.content = $content, m.status = $status, m.version = $ver,
                m.confidence = $conf,
                m.access_count = $ac, m.last_accessed_at = $laat,
                m.valid_until = $vu, m.superseded_by_id = $sbid,
                m.tags = $tags
                {emb_set_match}
            """,
            params,
        )

        # 确保 HAS_MEMORY 边
        try:
            await self._run_write(
                """
                MATCH (u:User {isolation_key: $ik}), (m:Memory {node_id: $nid})
                MERGE (u)-[:HAS_MEMORY]->(m)
                ON CREATE SET u.created_at = $now
                """,
                {"ik": isolation_key, "nid": node.node_id, "now": now},
            )
        except Exception as e:
            logger.debug(f"HAS_MEMORY edge note: {e}")

        return node.node_id

    async def get_node(self, node_id: str) -> Optional[MemoryNode]:
        """获取单个 Memory 节点"""
        row = await self._run_single(
            "MATCH (m:Memory {node_id: $nid}) RETURN m",
            {"nid": node_id},
        )
        if not row:
            return None
        return self._record_to_memory_node(row["m"])

    async def get_nodes_by_ids(self, node_ids: List[str]) -> List[MemoryNode]:
        """批量获取"""
        if not node_ids:
            return []
        rows = await self._run(
            "MATCH (m:Memory) WHERE m.node_id IN $nids RETURN m",
            {"nids": node_ids},
        )
        return [self._record_to_memory_node(r["m"]) for r in rows]

    async def get_all_nodes(
        self,
        isolation_key: str,
        layer: Optional[MemoryLayer] = None,
        status: Optional[MemoryStatus] = None,
        limit: int = 100,
    ) -> List[MemoryNode]:
        """按条件获取节点列表"""
        conditions = ["m.isolation_key = $ik"]
        params: Dict[str, Any] = {"ik": isolation_key, "lim": limit}

        if layer:
            conditions.append("m.layer = $layer")
            params["layer"] = layer.value
        if status:
            conditions.append("m.status = $status")
            params["status"] = status.value

        where = " AND ".join(conditions)
        rows = await self._run(
            f"MATCH (m:Memory) WHERE {where} RETURN m LIMIT $lim",
            params,
        )
        return [self._record_to_memory_node(r["m"]) for r in rows]

    async def get_profile(self, isolation_key: str) -> Optional[MemoryNode]:
        """获取 L5 Identity Profile 节点"""
        row = await self._run_single(
            "MATCH (m:Memory) WHERE m.isolation_key = $ik AND m.layer = $layer "
            "AND m.status = 'active' RETURN m LIMIT 1",
            {"ik": isolation_key, "layer": MemoryLayer.L4_IDENTITY.value},
        )
        if not row:
            return None
        return self._record_to_memory_node(row["m"])

    async def update_node(self, node_id: str, updates: Dict[str, Any]) -> bool:
        """更新节点属性"""
        if not updates:
            return True
        set_clauses = []
        params: Dict[str, Any] = {"nid": node_id}
        for key, value in updates.items():
            safe_key = key.replace("-", "_")
            set_clauses.append(f"m.{safe_key} = ${safe_key}")
            params[safe_key] = value

        set_str = ", ".join(set_clauses)
        try:
            await self._run_write(
                f"MATCH (m:Memory {{node_id: $nid}}) SET {set_str}",
                params,
            )
            return True
        except Exception as e:
            logger.warning(f"update_node failed for {node_id}: {e}")
            return False

    async def delete_node(self, node_id: str) -> bool:
        """删除 Memory 节点及其关联边"""
        try:
            await self._run_write(
                "MATCH (m:Memory {node_id: $nid}) DETACH DELETE m",
                {"nid": node_id},
            )
            return True
        except Exception as e:
            logger.warning(f"delete_node failed for {node_id}: {e}")
            return False

    async def delete_all_nodes(self, isolation_key: str) -> int:
        """删除某隔离键下所有 Memory 节点"""
        try:
            count_row = await self._run_single(
                "MATCH (m:Memory) WHERE m.isolation_key = $ik RETURN count(m) AS cnt",
                {"ik": isolation_key},
            )
            count = count_row["cnt"] if count_row else 0

            await self._run_write(
                "MATCH (m:Memory) WHERE m.isolation_key = $ik DETACH DELETE m",
                {"ik": isolation_key},
            )
            return count
        except Exception as e:
            logger.warning(f"delete_all_nodes failed for {isolation_key}: {e}")
            return 0

    async def delete_by_metadata(
        self,
        user_id: str,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """按 metadata 字段组合删除 Memory 节点"""
        try:
            conditions = ["m.user_id = $uid"]
            params: Dict[str, Any] = {"uid": user_id}
            if agent_id is not None:
                conditions.append("m.agent_id = $aid")
                params["aid"] = agent_id
            if session_id is not None:
                # Graph store Memory 节点不直接存 session_id，
                # 但 isolation_key = "user_id::agent_id::session_id"，
                # 构建精确的 isolation_key 来过滤
                ik = f"{user_id}::{agent_id or 'default_agent'}::{session_id}"
                conditions.append("m.isolation_key = $ik")
                params["ik"] = ik

            where = " AND ".join(conditions)

            count_row = await self._run_single(
                f"MATCH (m:Memory) WHERE {where} RETURN count(m) AS cnt",
                params,
            )
            count = count_row["cnt"] if count_row else 0

            await self._run_write(
                f"MATCH (m:Memory) WHERE {where} DETACH DELETE m",
                params,
            )

            user_conds = ["u.user_id = $uid"]
            user_params: Dict[str, Any] = {"uid": user_id}
            if session_id is not None:
                ik = f"{user_id}::{agent_id or 'default_agent'}::{session_id}"
                user_conds.append("u.isolation_key = $ik")
                user_params["ik"] = ik
            elif agent_id is not None:
                user_conds.append("u.agent_id = $aid")
                user_params["aid"] = agent_id
            await self._run_write(
                f"MATCH (u:User) WHERE {' AND '.join(user_conds)} DETACH DELETE u",
                user_params,
            )

            topic_params: Dict[str, Any] = {"pfx": f"{user_id}::"}
            if agent_id is not None and session_id is None:
                topic_params["pfx"] = f"{user_id}::{agent_id}::"
            elif session_id is not None:
                topic_params["pfx"] = f"{user_id}::{agent_id or 'default_agent'}::{session_id}"
                await self._run_write(
                    "MATCH (t:Topic) WHERE t.isolation_key = $pfx DETACH DELETE t",
                    topic_params,
                )
            else:
                await self._run_write(
                    "MATCH (t:Topic) WHERE t.isolation_key STARTS WITH $pfx DETACH DELETE t",
                    topic_params,
                )

            await self._run_write(
                "MATCH (v:VdbRef) "
                "OPTIONAL MATCH ()-[r:DERIVED_FROM]->(v) "
                "WITH v, count(r) AS cnt WHERE cnt = 0 "
                "DETACH DELETE v",
                {},
            )

            logger.info(
                f"[graph-store] delete_by_metadata user={user_id} agent={agent_id} "
                f"session={session_id} memory_nodes={count}"
            )
            return count
        except Exception as e:
            logger.warning(f"delete_by_metadata failed (user_id={user_id}): {e}")
            return 0

    # ================================================================
    # 边操作
    # ================================================================

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """添加 Memory→Memory 关系边；RELATED_TO 双向，认知关系保持方向。"""
        from .graph_relations import MEMORY_EDGE_TYPES, RELATED_TO
        props = properties or {}
        now = datetime.now().isoformat()

        edge_type_upper = edge_type.upper()
        if edge_type_upper not in MEMORY_EDGE_TYPES:
            logger.debug(f"Unsupported edge type: {edge_type}")
            return False

        params = {
            "src": source_id, "tgt": target_id,
            "rtype": props.get("relation_type", "related"),
            "w": props.get("weight", 1.0),
            "now": now,
        }

        try:
            reverse_clause = "" if edge_type_upper != RELATED_TO else f"""
                CREATE (b)-[:{edge_type_upper} {{
                    relation_type: $rtype, weight: $w, created_at: $now
                }}]->(a)
            """
            await self._run_write(
                f"""
                MATCH (a:Memory {{node_id: $src}}), (b:Memory {{node_id: $tgt}})
                CREATE (a)-[:{edge_type_upper} {{
                    relation_type: $rtype, weight: $w, created_at: $now
                }}]->(b)
                {reverse_clause}
                """,
                params,
            )
            return True
        except Exception as e:
            logger.warning(f"add_edge failed ({source_id})-[{edge_type}]->({target_id}): {e}")
            return False

    async def normalize_legacy_cognitive_edges(
        self,
        isolation_key: str,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Remove generated reverse CORRECTED edges when node chronology is decisive."""
        rows = await self._run(
            """
            MATCH (a:Memory)-[:CORRECTED]->(b:Memory),
                  (b)-[:CORRECTED]->(a)
            WHERE a.isolation_key = $ik AND b.isolation_key = $ik
              AND a.node_id < b.node_id
            RETURN a.node_id AS a_id, a.memory_at AS a_time,
                   b.node_id AS b_id, b.memory_at AS b_time
            """,
            {"ik": isolation_key},
        )
        corrected = []
        ambiguous = []
        seen_pairs = set()
        for row in rows:
            a_id, a_time = row["a_id"], row.get("a_time")
            b_id, b_time = row["b_id"], row.get("b_time")
            pair = (a_id, b_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if not a_time or not b_time or a_time == b_time:
                ambiguous.append({"edge_type": "CORRECTED", "nodes": [a_id, b_id]})
                continue
            newer, older = (a_id, b_id) if a_time > b_time else (b_id, a_id)
            corrected.append({"keep": [newer, older], "remove": [older, newer]})

        applied = 0
        if not dry_run:
            for item in corrected:
                await self._run_write(
                    """
                    MATCH (older:Memory {node_id: $older})-[r:CORRECTED]->
                          (newer:Memory {node_id: $newer})
                    DELETE r
                    """,
                    {"older": item["remove"][0], "newer": item["remove"][1]},
                )
                applied += 1
        return {"dry_run": dry_run, "corrected": corrected, "ambiguous": ambiguous, "applied": applied}

    async def migrate_legacy_related_edges(
        self,
        isolation_key: str,
        dry_run: bool = True,
        max_edges: int = 500,
    ) -> Dict[str, Any]:
        """Conservatively migrate old bidirectional RELATED_TO edges into cognitive edge types."""
        rows = await self._run(
            """
            MATCH (a:Memory)-[r:RELATED_TO]->(b:Memory),
                  (b)-[:RELATED_TO]->(a)
            WHERE a.isolation_key = $ik AND b.isolation_key = $ik
              AND a.node_id < b.node_id
            RETURN a.node_id AS a_id, a.memory_at AS a_time,
                   b.node_id AS b_id, b.memory_at AS b_time,
                   r.relation_type AS reason, r.weight AS weight
            LIMIT $limit
            """,
            {"ik": isolation_key, "limit": int(max_edges)},
        )
        migrate = []
        ambiguous = []
        skipped = 0
        for row in rows:
            a_id, a_time = row["a_id"], row.get("a_time")
            b_id, b_time = row["b_id"], row.get("b_time")
            reason = row.get("reason") or ""
            weight = row.get("weight") if row.get("weight") is not None else 1.0
            edge_type = infer_cognitive_edge_type_from_reason(reason)
            if edge_type == RELATED_TO:
                skipped += 1
                continue
            direction = plan_legacy_related_direction(edge_type, a_id, a_time, b_id, b_time)
            item = {
                "edge_type": edge_type,
                "nodes": [a_id, b_id],
                "reason": reason,
                "weight": weight,
            }
            if direction.get("status") == "migrate":
                item.update({"source": direction["source"], "target": direction["target"]})
                migrate.append(item)
            else:
                item["ambiguous_reason"] = direction.get("reason", "unknown")
                ambiguous.append(item)

        applied = 0
        if not dry_run:
            for item in migrate:
                await self._run_write(
                    """
                    MATCH (a:Memory {node_id: $a})-[r:RELATED_TO]->(b:Memory {node_id: $b})
                    DELETE r
                    """,
                    {"a": item["nodes"][0], "b": item["nodes"][1]},
                )
                await self._run_write(
                    """
                    MATCH (a:Memory {node_id: $b})-[r:RELATED_TO]->(b:Memory {node_id: $a})
                    DELETE r
                    """,
                    {"a": item["nodes"][0], "b": item["nodes"][1]},
                )
                if await self.add_edge(
                    item["source"],
                    item["target"],
                    item["edge_type"],
                    {"relation_type": item["reason"], "weight": item["weight"]},
                ):
                    applied += 1
        return {
            "dry_run": dry_run,
            "migrate": migrate,
            "ambiguous": ambiguous,
            "skipped": skipped,
            "applied": applied,
        }

    async def audit_duplicate_schema_nodes(
        self,
        isolation_key: str,
        threshold: float = 0.95,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Find high-similarity active L6 Schema nodes without mutating graph data."""
        rows = await self._run(
            """
            MATCH (m:Memory)
            WHERE m.isolation_key = $ik AND m.status = 'active'
              AND m.layer = 'l6_schema' AND m.embedding IS NOT NULL
            RETURN m.node_id AS node_id, m.content AS content,
                   m.memory_at AS memory_at, m.embedding AS embedding
            LIMIT $limit
            """,
            {"ik": isolation_key, "limit": int(limit)},
        )
        nodes = [
            {
                "node_id": row["node_id"],
                "content": row["content"],
                "memory_at": row.get("memory_at"),
                "embedding": row.get("embedding"),
            }
            for row in rows
        ]
        pairs = []
        parent = {node["node_id"]: node["node_id"] for node in nodes}

        def find(node_id: str) -> str:
            while parent[node_id] != node_id:
                parent[node_id] = parent[parent[node_id]]
                node_id = parent[node_id]
            return node_id

        def union(left: str, right: str) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for i, left in enumerate(nodes):
            for right in nodes[i + 1:]:
                score = cosine_similarity(left["embedding"], right["embedding"])
                if score >= threshold:
                    pairs.append({
                        "score": score,
                        "nodes": [
                            {"node_id": left["node_id"], "content": left["content"], "memory_at": left["memory_at"]},
                            {"node_id": right["node_id"], "content": right["content"], "memory_at": right["memory_at"]},
                        ],
                    })
                    union(left["node_id"], right["node_id"])

        grouped = {}
        content_by_id = {node["node_id"]: node for node in nodes}
        for node in nodes:
            root = find(node["node_id"])
            grouped.setdefault(root, []).append(node["node_id"])
        groups = [
            [
                {
                    "node_id": node_id,
                    "content": content_by_id[node_id]["content"],
                    "memory_at": content_by_id[node_id]["memory_at"],
                }
                for node_id in node_ids
            ]
            for node_ids in grouped.values()
            if len(node_ids) > 1
        ]
        return {"threshold": threshold, "pairs": pairs, "groups": groups}

    async def graph_health_snapshot(
        self,
        isolation_key: str,
        duplicate_threshold: float = 0.95,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """Return read-only health metrics for active L6 Schema graph quality."""
        rows = await self._run(
            """
            MATCH (m:Memory)
            WHERE m.isolation_key = $ik AND m.status = 'active'
              AND m.layer = 'l6_schema'
            RETURN m.node_id AS node_id
            LIMIT $limit
            """,
            {"ik": isolation_key, "limit": int(limit)},
        )
        schema_ids = [row["node_id"] for row in rows]
        schema_set = set(schema_ids)

        edge_type_counts: Dict[str, int] = {}
        connected = set()
        for edge_type in sorted(MEMORY_EDGE_TYPES):
            edge_rows = await self._run(
                f"""
                MATCH (a:Memory)-[r:{edge_type}]->(b:Memory)
                WHERE a.isolation_key = $ik AND b.isolation_key = $ik
                  AND a.status = 'active' AND b.status = 'active'
                  AND a.layer = 'l6_schema' AND b.layer = 'l6_schema'
                RETURN a.node_id AS source, b.node_id AS target
                """,
                {"ik": isolation_key},
            )
            related_pairs = set()
            count = 0
            for row in edge_rows:
                left, right = row["source"], row["target"]
                connected.add(left)
                connected.add(right)
                if edge_type == RELATED_TO:
                    related_pairs.add(tuple(sorted((left, right))))
                else:
                    count += 1
            edge_type_counts[edge_type] = len(related_pairs) if edge_type == RELATED_TO else count

        no_evidence = 0
        for node_id in schema_ids:
            if not await self.get_evidence_vdbrefs(node_id):
                no_evidence += 1

        duplicate_audit = await self.audit_duplicate_schema_nodes(
            isolation_key=isolation_key,
            threshold=duplicate_threshold,
            limit=limit,
        )
        related_to_edges = edge_type_counts.get(RELATED_TO, 0)
        memory_edge_total = sum(edge_type_counts.values())
        cognitive_edge_total = sum(
            count for edge_type, count in edge_type_counts.items()
            if edge_type in COGNITIVE_EDGE_TYPES
        )
        return {
            "schema_total": len(schema_ids),
            "duplicate_groups": len(duplicate_audit.get("groups", [])),
            "duplicate_pairs": len(duplicate_audit.get("pairs", [])),
            "edge_type_counts": edge_type_counts,
            "memory_edge_total": memory_edge_total,
            "cognitive_edge_total": cognitive_edge_total,
            "related_to_edges": related_to_edges,
            "related_to_ratio": round(related_to_edges / memory_edge_total, 4) if memory_edge_total else 0.0,
            "orphan_schema_count": len(schema_set - connected),
            "no_evidence_schema_count": no_evidence,
        }

    async def add_topic_tag(
        self,
        memory_node_id: str,
        topic_name: str,
        isolation_key: str,
        embed_service=None,
        similarity_threshold: float = 0.85,
    ) -> str:
        """记忆节点关联主题 (Memory→Topic)，支持 Tag 归一化

        如果传入 embed_service：
          1. embed 新 tag
          2. 和已有 Topic（同 isolation_key）做 cosine 比对
          3. 超过 similarity_threshold → 复用已有 Topic
          4. 否则新建 Topic（带 embedding）

        不传 embed_service 时退化为原始行为（按 name 精确匹配）。
        """
        import uuid as _uuid
        import numpy as np
        now = datetime.now().isoformat()

        # --- Tag 归一化 ---
        if embed_service is not None:
            try:
                tag_embedding = await embed_service.embed(topic_name)

                # 拉取已有 Topic
                existing = await self.get_all_topics(isolation_key)
                best_match = None
                best_sim = 0.0

                if existing and tag_embedding:
                    q_vec = np.array(tag_embedding, dtype=np.float32)
                    q_norm = np.linalg.norm(q_vec) + 1e-10
                    for t in existing:
                        t_emb = t.get("embedding")
                        if not t_emb:
                            continue
                        t_vec = np.array(t_emb, dtype=np.float32)
                        t_norm = np.linalg.norm(t_vec) + 1e-10
                        sim = float(np.dot(q_vec, t_vec) / (q_norm * t_norm))
                        if sim > best_sim:
                            best_sim = sim
                            best_match = t

                if best_match and best_sim >= similarity_threshold:
                    # 复用已有 Topic
                    topic_id = best_match["topic_id"]
                    logger.debug(
                        f"[tag-normalize] '{topic_name}' → reuse '{best_match['name']}' "
                        f"(sim={best_sim:.3f})"
                    )
                else:
                    # 新建 Topic（带 embedding）
                    topic_id = f"topic_{_uuid.uuid5(_uuid.NAMESPACE_URL, f'{isolation_key}:{topic_name}').hex[:12]}"
                    await self._run_write(
                        """
                        MERGE (t:Topic {topic_id: $tid})
                        ON CREATE SET t.isolation_key = $ik, t.name = $name,
                                      t.created_at = $now, t.embedding = $emb
                        """,
                        {"tid": topic_id, "ik": isolation_key, "name": topic_name,
                         "now": now, "emb": tag_embedding},
                    )
                    logger.debug(f"[tag-normalize] '{topic_name}' → new Topic (no match >= {similarity_threshold})")

                # 建 TAGGED_WITH 边（MERGE 防重复）
                await self._run_write(
                    """
                    MATCH (m:Memory {node_id: $mid}), (t:Topic {topic_id: $tid})
                    MERGE (m)-[:TAGGED_WITH]->(t)
                    """,
                    {"mid": memory_node_id, "tid": topic_id},
                )
                return topic_id

            except Exception as e:
                logger.warning(f"[tag-normalize] failed, fallback to exact match: {e}")
                # fallback 到下面的原始逻辑

        # --- 原始逻辑（无 embed_service 时） ---
        topic_id = f"topic_{_uuid.uuid5(_uuid.NAMESPACE_URL, f'{isolation_key}:{topic_name}').hex[:12]}"
        try:
            await self._run_write(
                """
                MERGE (t:Topic {topic_id: $tid})
                ON CREATE SET t.isolation_key = $ik, t.name = $name, t.created_at = $now
                """,
                {"tid": topic_id, "ik": isolation_key, "name": topic_name, "now": now},
            )
            await self._run_write(
                """
                MATCH (m:Memory {node_id: $mid}), (t:Topic {topic_id: $tid})
                MERGE (m)-[:TAGGED_WITH]->(t)
                """,
                {"mid": memory_node_id, "tid": topic_id},
                {"mid": memory_node_id, "tid": topic_id, "now": now},
            )
        except Exception as e:
            logger.debug(f"add_topic_tag note: {e}")

        return topic_id

    # ================================================================
    # Topic 检索 (Tag 收敛 + Tag 桥接召回)
    # ================================================================

    async def get_all_topics(self, isolation_key: str) -> List[Dict[str, Any]]:
        """获取某 isolation_key 下的所有 Topic 节点"""
        try:
            rows = await self._run(
                "MATCH (t:Topic {isolation_key: $ik}) "
                "RETURN t.topic_id AS topic_id, t.name AS name, t.embedding AS embedding",
                {"ik": isolation_key},
            )
            return [
                {"topic_id": r["topic_id"], "name": r["name"], "embedding": r.get("embedding")}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"get_all_topics failed: {e}")
            return []

    async def tag_bridge_search(
        self,
        topic_ids: List[str],
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Tag 桥接召回：从 Topic 反向查 TAGGED_WITH → Memory"""
        if not topic_ids:
            return []
        try:
            rows = await self._run(
                """
                MATCH (t:Topic)<-[:TAGGED_WITH]-(m:Memory)
                WHERE t.topic_id IN $tids AND m.status = 'active'
                RETURN DISTINCT m.node_id AS node_id, m.content AS content,
                       m.layer AS layer, m.confidence AS confidence,
                       t.name AS topic_name, m.custom_json AS custom_json
                LIMIT $lim
                """,
                {"tids": topic_ids, "lim": limit},
            )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"tag_bridge_search failed: {e}")
            return []

    # ================================================================
    # V3: VdbRef (shadow node) + DERIVED_FROM edge
    # ================================================================

    async def ensure_vdbref(self, node_id: str, layer: str) -> None:
        """确保 VdbRef 影子节点存在"""
        try:
            await self._run_write(
                "MERGE (v:VdbRef {node_id: $nid}) ON CREATE SET v.layer = $layer",
                {"nid": node_id, "layer": layer},
            )
        except Exception as e:
            logger.debug(f"ensure_vdbref note: {e}")

    async def add_derived_from(self, memory_node_id: str, vdbref_node_id: str) -> bool:
        """添加 DERIVED_FROM 边: Memory → VdbRef"""
        try:
            now = datetime.now().isoformat()
            await self._run_write(
                """
                MATCH (m:Memory {node_id: $mid}), (v:VdbRef {node_id: $vid})
                CREATE (m)-[:DERIVED_FROM {created_at: $now}]->(v)
                """,
                {"mid": memory_node_id, "vid": vdbref_node_id, "now": now},
            )
            return True
        except Exception as e:
            logger.warning(f"add_derived_from failed ({memory_node_id})->({vdbref_node_id}): {e}")
            return False

    async def find_referencing_memories(
        self,
        vdb_node_ids: List[str],
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """反向查找: VDB node_id → 引用它的 Graph Memory 节点"""
        if not vdb_node_ids:
            return []
        results = []
        for vdb_id in vdb_node_ids:
            try:
                rows = await self._run(
                    """
                    MATCH (v:VdbRef {node_id: $vid})<-[:DERIVED_FROM]-(m:Memory)
                    WHERE m.status = 'active'
                    RETURN m.node_id AS node_id, m.content AS content,
                           m.layer AS layer, m.confidence AS confidence,
                           m.custom_json AS custom_json
                    LIMIT $limit
                    """,
                    {"vid": vdb_id, "limit": limit},
                )
                for row in rows:
                    results.append({
                        "node_id": row["node_id"],
                        "content": row["content"],
                        "layer": row["layer"],
                        "confidence": row["confidence"],
                        "custom_json": row.get("custom_json", ""),
                        "evidence_vdb_id": vdb_id,
                        "source": "reverse_evidence",
                    })
            except Exception as e:
                logger.debug(f"find_referencing_memories for {vdb_id}: {e}")
        return results[:limit]

    async def get_evidence_vdbrefs(self, memory_node_id: str) -> List[Dict[str, Any]]:
        """获取一个 Graph Memory 的全部 DERIVED_FROM evidence VdbRef"""
        try:
            rows = await self._run(
                """
                MATCH (m:Memory {node_id: $mid})-[:DERIVED_FROM]->(v:VdbRef)
                RETURN v.node_id AS node_id, v.layer AS layer
                """,
                {"mid": memory_node_id},
            )
            return [{"node_id": r["node_id"], "layer": r["layer"]} for r in rows]
        except Exception as e:
            logger.debug(f"get_evidence_vdbrefs for {memory_node_id}: {e}")
            return []

    # ================================================================
    # 图检索
    # ================================================================

    async def expand_from_anchors(
        self,
        anchor_ids: List[str],
        hop: int = 1,
        max_nodes: int = 50,
    ) -> List[Dict[str, Any]]:
        """从锚点节点出发，沿图边扩展 N 跳"""
        if not anchor_ids:
            return []

        expanded = []
        seen = set(anchor_ids)

        for anchor_id in anchor_ids:
            try:
                # 正向边
                rows = await self._run(
                    """
                    MATCH (a:Memory {node_id: $aid})-[r]->(b:Memory)
                    WHERE b.status = 'active'
                    RETURN b.node_id AS node_id, b.content AS content,
                           b.layer AS layer, b.confidence AS confidence,
                           type(r) AS edge_type, r.relation_type AS reason,
                           r.weight AS weight
                    LIMIT $lim
                    """,
                    {"aid": anchor_id, "lim": max_nodes},
                )
                for row in rows:
                    nid = row["node_id"]
                    if nid not in seen:
                        seen.add(nid)
                        expanded.append({
                            "node_id": nid,
                            "content": row["content"],
                            "layer": row["layer"],
                            "confidence": row["confidence"],
                            "edge_type": row["edge_type"],
                            "reason": row.get("reason"),
                            "weight": row.get("weight"),
                            "direction": "outgoing",
                            "from_anchor": anchor_id,
                            "source": "graph_expand",
                        })

                # 反向边
                rows2 = await self._run(
                    """
                    MATCH (b:Memory)-[r]->(a:Memory {node_id: $aid})
                    WHERE b.status = 'active'
                    RETURN b.node_id AS node_id, b.content AS content,
                           b.layer AS layer, b.confidence AS confidence,
                           type(r) AS edge_type, r.relation_type AS reason,
                           r.weight AS weight
                    LIMIT $lim
                    """,
                    {"aid": anchor_id, "lim": max_nodes},
                )
                for row in rows2:
                    nid = row["node_id"]
                    if nid not in seen:
                        seen.add(nid)
                        expanded.append({
                            "node_id": nid,
                            "content": row["content"],
                            "layer": row["layer"],
                            "confidence": row["confidence"],
                            "edge_type": row["edge_type"],
                            "reason": row.get("reason"),
                            "weight": row.get("weight"),
                            "direction": "incoming",
                            "from_anchor": anchor_id,
                            "source": "graph_expand",
                        })

            except Exception as e:
                logger.debug(f"expand_from_anchors for {anchor_id}: {e}")

            if len(expanded) >= max_nodes:
                break

        return expanded[:max_nodes]

    async def expand_with_tags(
        self,
        anchor_ids: List[str],
        hop: int = 2,
        max_nodes: int = 500,
        isolation_key: str = "",
    ) -> List[Dict[str, Any]]:
        """BFS 展开：RELATED_TO + CROSS_ABSTRACTS_TO + TAGGED_WITH，N 跳。

        每一跳同时查：
        1. Memory -[RELATED_TO]- Memory（双向）
        2. Memory -[CROSS_ABSTRACTS_TO]- Memory（双向，basic↔abstract）
        3. Memory -[TAGGED_WITH]-> Topic <-[TAGGED_WITH]- Memory（经 Topic 桥接）

        所有结果必须是 Memory 节点（不返回 Topic/VdbRef 等中间节点）。
        isolation_key 非空时只展开属于同一 isolation_key 的节点。
        """
        if not anchor_ids:
            return []

        seen = set(anchor_ids)
        all_expanded = []
        frontier = list(anchor_ids)

        # isolation_key 过滤条件
        ik_filter = "AND m.isolation_key = $ik" if isolation_key else ""
        params_base = {"ik": isolation_key} if isolation_key else {}

        for current_hop in range(1, hop + 1):
            if not frontier or len(all_expanded) >= max_nodes:
                break

            next_frontier = []

            # --- RELATED_TO + CROSS_ABSTRACTS_TO 邻居（双向，合并查询）---
            try:
                rows = await self._run(
                    f"""
                    UNWIND $ids AS aid
                    MATCH (a:Memory {{node_id: aid}})-[:RELATED_TO|CROSS_ABSTRACTS_TO]-(m:Memory)
                    WHERE m.status = 'active' {ik_filter}
                    RETURN DISTINCT m.node_id AS node_id, m.content AS content,
                           m.layer AS layer, m.confidence AS confidence,
                           m.custom_json AS custom_json
                    """,
                    {"ids": frontier, **params_base},
                )
                for row in rows:
                    nid = row["node_id"]
                    if nid not in seen:
                        seen.add(nid)
                        all_expanded.append({
                            "node_id": nid,
                            "content": row["content"],
                            "layer": row["layer"],
                            "confidence": row["confidence"],
                            "custom_json": row.get("custom_json", ""),
                            "hop": current_hop,
                            "source": "related_to",
                        })
                        next_frontier.append(nid)
            except Exception as e:
                logger.debug(f"expand_with_tags RELATED_TO|CROSS_ABSTRACTS_TO hop {current_hop}: {e}")

            # --- TAGGED_WITH 桥接（Memory→Topic→Memory）---
            try:
                rows = await self._run(
                    f"""
                    UNWIND $ids AS aid
                    MATCH (a:Memory {{node_id: aid}})-[:TAGGED_WITH]->(t:Topic)<-[:TAGGED_WITH]-(m:Memory)
                    WHERE m.status = 'active' AND m.node_id <> aid {ik_filter}
                    RETURN DISTINCT m.node_id AS node_id, m.content AS content,
                           m.layer AS layer, m.confidence AS confidence,
                           m.custom_json AS custom_json, t.name AS via_tag
                    """,
                    {"ids": frontier, **params_base},
                )
                for row in rows:
                    nid = row["node_id"]
                    if nid not in seen:
                        seen.add(nid)
                        all_expanded.append({
                            "node_id": nid,
                            "content": row["content"],
                            "layer": row["layer"],
                            "confidence": row["confidence"],
                            "custom_json": row.get("custom_json", ""),
                            "hop": current_hop,
                            "source": f"tag:{row['via_tag']}",
                        })
                        next_frontier.append(nid)
            except Exception as e:
                logger.debug(f"expand_with_tags TAGGED_WITH hop {current_hop}: {e}")

            frontier = next_frontier

        return all_expanded[:max_nodes]

    # ================================================================
    # 向量检索 (HNSW 双索引)
    # ================================================================

    async def vector_search(
        self,
        query_embedding: List[float],
        isolation_key: str,
        layers: Optional[List[str]] = None,
        limit: int = 10,
        score_threshold: float = 0.0,
        user_id: str = "",
    ) -> List[Dict[str, Any]]:
        """V_con 向量检索 Graph Memory 节点 — **Pre-Filter 模式**

        使用 Neo4j 5.18+ 的 ``vector.similarity.cosine()`` 函数，
        先按 isolation_key / layer / status 做 MATCH 过滤，
        再在过滤后的子集上计算向量相似度。

        与旧的 ``db.index.vector.queryNodes()`` 方案相比：
        - queryNodes 是全局 HNSW top-K → post-filter，稀疏用户召回率极低
        - 本方案是 pre-filter → brute-force cosine，保证 100% 召回率
        - 性能差异 <10ms（用户级节点数通常 <100），完全可接受

        当 isolation_key 为空但 user_id 非空时，执行跨 agent 搜索
        （匹配 isolation_key 以 user_id + "::" 为前缀的所有节点）。
        """
        if self._driver is None or not query_embedding:
            return []

        try:
            # layer 过滤
            layer_filter = ""
            if layers:
                layer_list = ", ".join(f"'{l}'" for l in layers)
                layer_filter = f"AND m.layer IN [{layer_list}]"

            # 隔离过滤：精确 ik 或 user_id 前缀
            if isolation_key:
                ik_filter = "m.isolation_key = $ik"
            elif user_id:
                ik_filter = "m.isolation_key STARTS WITH $ik"
                isolation_key = user_id + "::"
            else:
                return []

            rows = await self._run(
                f"""
                MATCH (m:Memory)
                WHERE {ik_filter} AND m.status = 'active'
                    {layer_filter}
                    AND m.embedding IS NOT NULL
                WITH m, vector.similarity.cosine(m.embedding, $vec) AS score
                WHERE score >= $threshold
                RETURN m.node_id AS node_id, m.content AS content,
                       m.layer AS layer, m.confidence AS confidence,
                       score, m.custom_json AS custom_json
                ORDER BY score DESC
                LIMIT $lim
                """,
                {
                    "vec": query_embedding,
                    "ik": isolation_key,
                    "threshold": (1.0 + score_threshold) / 2.0,  # 原始 cosine → Neo4j (1+cos)/2 尺度
                    "lim": limit,
                },
            )

            # Neo4j vector.similarity.cosine() 返回 (1+cos)/2 ∈ [0,1]，
            # 转换为原始 cosine similarity [-1,1]（与 Qdrant 统一尺度）：
            #   raw_cosine = 2 * neo4j_score - 1
            return [
                {
                    "node_id": r["node_id"],
                    "content": r["content"],
                    "layer": r["layer"],
                    "confidence": r["confidence"],
                    "score": 2.0 * r["score"] - 1.0,
                    "custom_json": r["custom_json"],
                    "source": "graph_vector_search",
                }
                for r in rows
            ]

        except Exception as e:
            logger.warning(f"vector_search failed: {e}")
            return []

    async def beh_vector_search(
        self,
        query_beh_embedding: List[float],
        isolation_key: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """V_beh 向量检索 L6 basic 节点 — **Pre-Filter 模式**

        使用 ``vector.similarity.cosine()`` 对 beh_embedding 做
        isolation_key pre-filter 后的精确向量搜索。
        """
        if self._driver is None or not query_beh_embedding:
            return []

        try:
            rows = await self._run(
                """
                MATCH (m:Memory {isolation_key: $ik})
                WHERE m.status = 'active' AND m.layer = 'l6_schema'
                    AND m.beh_embedding IS NOT NULL
                WITH m, vector.similarity.cosine(m.beh_embedding, $vec) AS score
                RETURN m.node_id AS node_id, m.content AS content,
                       m.embedding AS embedding,
                       score AS beh_score
                ORDER BY score DESC
                LIMIT $lim
                """,
                {
                    "vec": query_beh_embedding,
                    "ik": isolation_key,
                    "lim": limit,
                },
            )

            # beh_score 是 Neo4j 的 (1+cos)/2 ∈ [0,1]
            # distance = 1 - similarity，保持 0~1 尺度
            return [
                {
                    "node_id": r["node_id"],
                    "content": r["content"],
                    "embedding": r["embedding"],
                    "beh_distance": 1.0 - r["beh_score"],
                }
                for r in rows
            ]

        except Exception as e:
            logger.warning(f"beh_vector_search failed: {e}")
            return []

    async def update_embedding(
        self,
        node_id: str,
        embedding: Optional[List[float]] = None,
        beh_embedding: Optional[List[float]] = None,
    ) -> bool:
        """更新节点的 embedding / beh_embedding 向量属性

        Neo4j 允许 SET 被向量索引的属性，索引自动更新。
        """
        if self._driver is None:
            return False
        try:
            sets = []
            params: Dict[str, Any] = {"nid": node_id}
            if embedding is not None:
                sets.append("m.embedding = $emb")
                params["emb"] = embedding
            if beh_embedding is not None:
                sets.append("m.beh_embedding = $beh")
                params["beh"] = beh_embedding
            if not sets:
                return True
            set_str = ", ".join(sets)
            await self._run_write(
                f"MATCH (m:Memory {{node_id: $nid}}) SET {set_str}",
                params,
            )
            return True
        except Exception as e:
            logger.warning(f"update_embedding failed for {node_id}: {e}")
            return False

    # ================================================================
    # 跨域归纳 (Cross-Domain)
    # ================================================================

    async def add_cross_abstracts_to(self, basic_id: str, core_id: str) -> bool:
        """添加 CROSS_ABSTRACTS_TO 边: L6 basic → L6 core (单向)"""
        if self._driver is None:
            return False
        try:
            now = datetime.now().isoformat()
            await self._run_write(
                """
                MATCH (a:Memory {node_id: $src}), (b:Memory {node_id: $tgt})
                CREATE (a)-[:CROSS_ABSTRACTS_TO {created_at: $now}]->(b)
                """,
                {"src": basic_id, "tgt": core_id, "now": now},
            )
            return True
        except Exception as e:
            logger.warning(f"add_cross_abstracts_to failed ({basic_id})->({core_id}): {e}")
            return False

    async def find_cores_from_basics(
        self,
        basic_ids: List[str],
        max_hops: int = 2,
    ) -> List[Dict[str, Any]]:
        """从 L6 节点出发，沿 CROSS_ABSTRACTS_TO 找 higher-level 节点"""
        if self._driver is None or not basic_ids:
            return []

        try:
            rows = await self._run(
                f"""
                MATCH (start:Memory)
                      -[:CROSS_ABSTRACTS_TO*1..{int(max_hops)}]->
                      (core:Memory)
                WHERE start.node_id IN $nids
                  AND core.status = 'active'
                RETURN DISTINCT core.node_id AS node_id,
                       core.content AS content,
                       core.confidence AS confidence
                """,
                {"nids": basic_ids},
            )
            return [
                {
                    "node_id": r["node_id"],
                    "content": r["content"],
                    "confidence": r["confidence"],
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug(f"find_cores_from_basics failed: {e}")
            return []

    async def get_cross_abstracts_targets(self, basic_id: str) -> List[str]:
        """查询某个 L6 basic 已有的 CROSS_ABSTRACTS_TO → core node_id 列表"""
        if self._driver is None:
            return []
        try:
            rows = await self._run(
                """
                MATCH (a:Memory {node_id: $nid})-[:CROSS_ABSTRACTS_TO]->(b:Memory)
                RETURN b.node_id AS node_id
                """,
                {"nid": basic_id},
            )
            return [r["node_id"] for r in rows]
        except Exception as e:
            logger.debug(f"get_cross_abstracts_targets for {basic_id}: {e}")
            return []

    # ================================================================
    # 内部工具
    # ================================================================

    @staticmethod
    def _record_to_memory_node(node_data: Any) -> MemoryNode:
        """将 Neo4j Node 转为 MemoryNode"""
        # Neo4j driver 返回的 Node 对象支持 dict-like 访问
        if hasattr(node_data, 'items'):
            d = dict(node_data)
        elif isinstance(node_data, dict):
            d = node_data
        else:
            d = {}

        # 解析 JSON 字段
        evidence_chain = d.get("evidence_chain", "[]")
        if isinstance(evidence_chain, str):
            try:
                evidence_chain = json.loads(evidence_chain)
            except (json.JSONDecodeError, TypeError):
                evidence_chain = []

        custom = d.get("custom_json", "{}")
        if isinstance(custom, str):
            try:
                custom = json.loads(custom)
            except (json.JSONDecodeError, TypeError):
                custom = {}

        tags = d.get("tags", "[]")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []

        # 处理时间字段 - Neo4j 可能返回 ISO 字符串或 datetime
        def _parse_dt(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    return None
            # neo4j DateTime object
            if hasattr(val, 'to_native'):
                return val.to_native()
            return None

        return MemoryNode.from_dict({
            "node_id": d.get("node_id", ""),
            "user_id": d.get("user_id", ""),
            "agent_id": d.get("agent_id", ""),
            "layer": d.get("layer", "l1_raw"),
            "content": d.get("content", ""),
            "status": d.get("status", "active"),
            "version": d.get("version", 1),
            "confidence": d.get("confidence", 1.0),
            "access_count": d.get("access_count", 0),
            "created_at": _parse_dt(d.get("created_at")),
            "valid_from": _parse_dt(d.get("valid_from")),
            "valid_until": _parse_dt(d.get("valid_until")),
            "last_accessed_at": _parse_dt(d.get("last_accessed_at")),
            "superseded_by_id": d.get("superseded_by_id"),
            "evidence_chain": evidence_chain,
            "custom": custom,
            "tags": tags,
        })
