"""
Agent Memory V2 - MysqlCache

基于 aiomysql 的 MySQL 审计/观测落库后端。
适用于腾讯云 MySQL (CDB) 等标准 MySQL 实例，支持多实例共享状态。

设计模式：
- aiomysql 原生 async（无需线程池包装）
- 连接池 aiomysql.create_pool
- autocommit=True

三张表（与 SQLite 版本一一对应）：
- memory_operations: 知识库变动日志
- pipeline_logs:     LLM 调用链中间结果
- system_metrics:    分钟粒度系统指标
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from .cache_base import CacheBase
from ..config import MemoryConfig

logger = logging.getLogger(__name__)

# DDL (MySQL syntax)
_CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS memory_operations_v2 (
        id            BIGINT AUTO_INCREMENT,
        request_id    VARCHAR(128) NOT NULL,
        user_id       VARCHAR(128) NOT NULL,
        agent_id      VARCHAR(128) NOT NULL DEFAULT '',
        op            VARCHAR(32) NOT NULL,
        memory_id     VARCHAR(128) NOT NULL,
        old_memory_id VARCHAR(128) DEFAULT NULL,
        content       LONGTEXT NOT NULL,
        layer         VARCHAR(32) NOT NULL DEFAULT '',
        reason        TEXT NOT NULL,
        supersedes    TEXT NOT NULL,
        created_at    VARCHAR(64) NOT NULL,
        created_date  DATE NOT NULL,
        PRIMARY KEY (id, created_date),
        INDEX idx_memop_request (request_id),
        INDEX idx_memop_memory (memory_id),
        INDEX idx_memop_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    PARTITION BY RANGE (TO_DAYS(created_date)) (
        PARTITION pmax VALUES LESS THAN MAXVALUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_logs_v2 (
        id                BIGINT AUTO_INCREMENT,
        request_id        VARCHAR(128) NOT NULL,
        user_id           VARCHAR(128) NOT NULL,
        agent_id          VARCHAR(128) NOT NULL DEFAULT '',
        step              VARCHAR(64) NOT NULL,
        prompt            LONGTEXT NOT NULL,
        response          LONGTEXT NOT NULL,
        parsed            LONGTEXT NOT NULL,
        memory_ids        TEXT NOT NULL,
        elapsed_ms        DOUBLE NOT NULL DEFAULT 0,
        prompt_tokens     INT NOT NULL DEFAULT 0,
        completion_tokens INT NOT NULL DEFAULT 0,
        total_tokens      INT NOT NULL DEFAULT 0,
        created_at        VARCHAR(64) NOT NULL,
        created_date      DATE NOT NULL,
        PRIMARY KEY (id, created_date),
        INDEX idx_plog_request (request_id),
        INDEX idx_plog_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    PARTITION BY RANGE (TO_DAYS(created_date)) (
        PARTITION pmax VALUES LESS THAN MAXVALUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_metrics (
        minute_ts   VARCHAR(32) NOT NULL,
        data        LONGTEXT NOT NULL,
        created_at  VARCHAR(64) NOT NULL,
        PRIMARY KEY (minute_ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS digest_runs (
        run_id          VARCHAR(128) NOT NULL,
        user_id         VARCHAR(128) NOT NULL DEFAULT '',
        agent_id        VARCHAR(128) NOT NULL DEFAULT '',
        `trigger`       VARCHAR(32) NOT NULL DEFAULT '',
        status          VARCHAR(32) NOT NULL DEFAULT '',
        clusters_total  INT NOT NULL DEFAULT 0,
        batches         INT NOT NULL DEFAULT 0,
        tasks_total     INT NOT NULL DEFAULT 0,
        tasks_succeeded INT NOT NULL DEFAULT 0,
        tasks_failed    INT NOT NULL DEFAULT 0,
        retry_count     INT NOT NULL DEFAULT 0,
        error_message   TEXT NOT NULL,
        total_tokens    INT NOT NULL DEFAULT 0,
        started_at      VARCHAR(64) NOT NULL DEFAULT '',
        completed_at    VARCHAR(64) NOT NULL DEFAULT '',
        elapsed_ms      DOUBLE NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id),
        INDEX idx_drun_user (user_id),
        INDEX idx_drun_started (started_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


class MysqlCache(CacheBase):
    """
    MySQL 审计/观测落库后端（memory_operations / pipeline_logs / system_metrics）。

    基于 aiomysql 的原生异步 MySQL 后端，适用于腾讯云 MySQL (CDB)。
    """

    def __init__(self, config: MemoryConfig):
        self.config = config
        self._pool = None  # aiomysql.Pool

        # 读取 MySQL 连接参数
        cache_cfg = getattr(config, "cache", None)
        self._host = getattr(cache_cfg, "mysql_host", None) or os.getenv("MEMORY_MYSQL_HOST", "localhost")
        self._port = getattr(cache_cfg, "mysql_port", None) or int(os.getenv("MEMORY_MYSQL_PORT", "3306"))
        self._user = getattr(cache_cfg, "mysql_user", None) or os.getenv("MEMORY_MYSQL_USER", "root")
        self._password = getattr(cache_cfg, "mysql_password", None) or os.getenv("MEMORY_MYSQL_PASSWORD", "")
        self._database = getattr(cache_cfg, "mysql_database", None) or os.getenv("MEMORY_MYSQL_DATABASE", "hy_memory")
        self._pool_size = getattr(cache_cfg, "mysql_pool_size", None) or int(os.getenv("MEMORY_MYSQL_POOL_SIZE", "10"))
        self._pool_recycle = getattr(cache_cfg, "mysql_pool_recycle", None) or int(os.getenv("MEMORY_MYSQL_POOL_RECYCLE", "3600"))

    # ================================================================
    # 生命周期
    # ================================================================

    async def initialize(self) -> None:
        """立即创建 pool（必须在正确的 event loop 上调用，即 _LoopThread 的 loop）"""
        import aiomysql
        self._pool = await aiomysql.create_pool(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            db=self._database,
            minsize=2,
            maxsize=self._pool_size,
            pool_recycle=self._pool_recycle,
            autocommit=True,
            charset='utf8mb4',
        )
        await self._ensure_tables()
        logger.info(
            f"MysqlCache initialized: {self._user}@{self._host}:{self._port}/{self._database} "
            f"pool_size={self._pool_size}"
        )

    async def _ensure_tables(self) -> None:
        """确保所有表存在"""
        for ddl in _CREATE_TABLES_SQL:
            await self._execute(ddl)

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
        logger.info("MysqlCache closed")

    # ================================================================
    # 内部 DB helpers
    # ================================================================

    async def _execute(self, sql: str, args=None) -> int:
        """执行写操作，返回 affected rows"""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)
                return cur.rowcount

    async def _fetchone(self, sql: str, args=None) -> Optional[Dict[str, Any]]:
        """查询单行，返回 dict 或 None"""
        import aiomysql
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                row = await cur.fetchone()
                # 防御：极端情况下 DictCursor 可能返回 tuple
                if row is not None and not isinstance(row, dict):
                    cols = [d[0] for d in cur.description] if cur.description else []
                    row = dict(zip(cols, row))
                return row

    async def _fetchall(self, sql: str, args=None) -> List[Dict[str, Any]]:
        """查询多行，返回 list of dict"""
        import aiomysql
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                rows = await cur.fetchall()
                # 防御：确保返回 list of dict
                if rows and not isinstance(rows[0], dict):
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = [dict(zip(cols, r)) for r in rows]
                return rows

    # ================================================================
    # 统计
    # ================================================================

    async def get_stats(self) -> Dict[str, Any]:
        return {
            "backend": "mysql",
            "host": self._host,
            "database": self._database,
        }

    # ================================================================
    # Memory Operations Log
    # ================================================================

    async def store_memory_operation(
        self,
        request_id: str,
        user_id: str,
        agent_id: str,
        op: str,
        memory_id: str,
        content: str,
        layer: str = "",
        old_memory_id: Optional[str] = None,
        reason: str = "",
        supersedes: Optional[List[str]] = None,
    ) -> bool:
        from ..utils.pipeline_observability import is_memory_operations_enabled
        if not is_memory_operations_enabled():
            return True
        try:
            now = datetime.now()
            created_at = now.isoformat()
            created_date = now.strftime("%Y-%m-%d")
            supersedes_str = json.dumps(supersedes or [], ensure_ascii=False)
            await self._execute(
                """INSERT INTO memory_operations_v2
                   (request_id, user_id, agent_id, op, memory_id, old_memory_id,
                    content, layer, reason, supersedes, created_at, created_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (request_id, user_id, agent_id, op, memory_id,
                 old_memory_id, content, layer, reason, supersedes_str,
                 created_at, created_date),
            )
            return True
        except Exception as e:
            logger.warning(f"store_memory_operation failed: {e}")
            return False

    async def get_memory_operations(
        self,
        request_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            conditions = []
            params = []
            if request_id:
                conditions.append("request_id = %s")
                params.append(request_id)
            if memory_id:
                conditions.append("memory_id = %s")
                params.append(memory_id)
            if user_id:
                conditions.append("user_id = %s")
                params.append(user_id)

            if not conditions:
                return []

            where = " AND ".join(conditions)
            rows = await self._fetchall(
                f"SELECT * FROM memory_operations_v2 WHERE {where} "
                f"ORDER BY id DESC LIMIT %s",
                params + [limit],
            )
            # 反序列化 supersedes
            for row in rows:
                raw_sup = row.get("supersedes", "")
                try:
                    row["supersedes"] = json.loads(raw_sup) if raw_sup else []
                except Exception:
                    row["supersedes"] = []
            return rows
        except Exception as e:
            logger.warning(f"get_memory_operations failed: {e}")
            return []

    # ================================================================
    # Pipeline Logs
    # ================================================================

    async def store_pipeline_log(
        self,
        request_id: str,
        user_id: str,
        agent_id: str,
        step: str,
        prompt: str,
        response: str,
        parsed: str = "",
        memory_ids: Optional[List[str]] = None,
        elapsed_ms: float = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> bool:
        try:
            now = datetime.now()
            created_at = now.isoformat()
            created_date = now.strftime("%Y-%m-%d")
            mem_ids_json = json.dumps(memory_ids or [])
            await self._execute(
                """INSERT INTO pipeline_logs_v2
                   (request_id, user_id, agent_id, step, prompt, response,
                    parsed, memory_ids, elapsed_ms,
                    prompt_tokens, completion_tokens, total_tokens,
                    created_at, created_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (request_id, user_id, agent_id, step, prompt, response,
                 parsed, mem_ids_json, elapsed_ms,
                 prompt_tokens, completion_tokens, total_tokens,
                 created_at, created_date),
            )
            return True
        except Exception as e:
            logger.warning(f"store_pipeline_log failed: {e}")
            return False

    async def get_pipeline_logs(
        self,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        step: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        try:
            conditions = []
            params = []
            if request_id:
                conditions.append("request_id = %s")
                params.append(request_id)
            if user_id:
                conditions.append("user_id = %s")
                params.append(user_id)
            if step:
                conditions.append("step = %s")
                params.append(step)

            if not conditions:
                return []

            where = " AND ".join(conditions)
            rows = await self._fetchall(
                f"SELECT * FROM pipeline_logs_v2 WHERE {where} "
                f"ORDER BY id ASC LIMIT %s",
                params + [limit],
            )
            return rows
        except Exception as e:
            logger.warning(f"get_pipeline_logs failed: {e}")
            return []

    # ================================================================
    # Digest Runs（System 2 顶层执行记录）
    # ================================================================

    _DIGEST_RUN_COLS = (
        "run_id", "user_id", "agent_id", "trigger", "status",
        "clusters_total", "batches", "tasks_total", "tasks_succeeded",
        "tasks_failed", "retry_count", "error_message", "total_tokens",
        "started_at", "completed_at", "elapsed_ms",
    )
    _DIGEST_RUN_STR_COLS = {
        "user_id", "agent_id", "trigger", "status",
        "error_message", "started_at", "completed_at",
    }

    async def store_digest_run(self, run_id: str, record: Dict[str, Any]) -> bool:
        try:
            rec = dict(record)
            rec["run_id"] = run_id
            values = [
                rec.get(c, "" if c in self._DIGEST_RUN_STR_COLS else 0)
                for c in self._DIGEST_RUN_COLS
            ]
            cols = ", ".join(f"`{c}`" for c in self._DIGEST_RUN_COLS)
            placeholders = ", ".join("%s" for _ in self._DIGEST_RUN_COLS)
            await self._execute(
                f"REPLACE INTO digest_runs ({cols}) VALUES ({placeholders})",
                values,
            )
            return True
        except Exception as e:
            logger.warning(f"store_digest_run failed: {e}")
            return False

    async def update_digest_run(self, run_id: str, **fields: Any) -> bool:
        valid = [k for k in fields if k in self._DIGEST_RUN_COLS and k != "run_id"]
        if not valid:
            return False
        try:
            set_clause = ", ".join(f"`{k}` = %s" for k in valid)
            params = [fields[k] for k in valid] + [run_id]
            await self._execute(
                f"UPDATE digest_runs SET {set_clause} WHERE run_id = %s",
                params,
            )
            return True
        except Exception as e:
            logger.warning(f"update_digest_run failed: {e}")
            return False

    async def get_digest_runs(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        try:
            if user_id:
                return await self._fetchall(
                    "SELECT * FROM digest_runs WHERE user_id = %s "
                    "ORDER BY started_at DESC LIMIT %s",
                    [user_id, limit],
                )
            return await self._fetchall(
                "SELECT * FROM digest_runs ORDER BY started_at DESC LIMIT %s",
                [limit],
            )
        except Exception as e:
            logger.warning(f"get_digest_runs failed: {e}")
            return []

    # ================================================================
    # System Metrics（分钟粒度落盘）
    # ================================================================

    async def store_metrics_minute(self, minute_ts: str, data: dict) -> None:
        try:
            now = datetime.now().isoformat()
            # 尝试 UPSERT
            existing = await self._fetchone(
                "SELECT data FROM system_metrics WHERE minute_ts = %s", (minute_ts,)
            )
            if existing:
                old_data = json.loads(existing["data"])
                merged = self._merge_metric_buckets(old_data, data)
                await self._execute(
                    "UPDATE system_metrics SET data = %s, created_at = %s WHERE minute_ts = %s",
                    (json.dumps(merged, default=str), now, minute_ts),
                )
            else:
                await self._execute(
                    "INSERT INTO system_metrics (minute_ts, data, created_at) VALUES (%s, %s, %s)",
                    (minute_ts, json.dumps(data, default=str), now),
                )
        except Exception as e:
            logger.warning(f"store_metrics_minute failed: {e}")

    async def load_metrics_range(self, start_ts: str, end_ts: str) -> list:
        try:
            rows = await self._fetchall(
                "SELECT data FROM system_metrics WHERE minute_ts >= %s AND minute_ts <= %s ORDER BY minute_ts",
                (start_ts, end_ts),
            )
            results = []
            for row in rows:
                try:
                    results.append(json.loads(row["data"]))
                except (json.JSONDecodeError, TypeError):
                    pass
            return results
        except Exception as e:
            logger.warning(f"load_metrics_range failed: {e}")
            return []

    async def cleanup_old_metrics(self, before_ts: str) -> None:
        try:
            await self._execute(
                "DELETE FROM system_metrics WHERE minute_ts < %s", (before_ts,)
            )
        except Exception as e:
            logger.warning(f"cleanup_old_metrics failed: {e}")

    @staticmethod
    def _merge_metric_buckets(old: dict, new: dict) -> dict:
        """合并两个 metric bucket（同一分钟多次 flush）"""
        merged = dict(old)
        for key in ("sys1_started", "sys1_completed", "sys1_failed",
                    "sys2_started", "sys2_completed", "sys2_failed",
                    "vdb_ops", "graph_ops"):
            merged[key] = merged.get(key, 0) + new.get(key, 0)
        for key in ("vdb_ops_sum_ms", "graph_ops_sum_ms"):
            merged[key] = merged.get(key, 0) + new.get(key, 0)
        # timing sums
        for bucket_key in ("sys1_timing_sums", "sys2_timing_sums"):
            old_sums = merged.get(bucket_key, {})
            new_sums = new.get(bucket_key, {})
            for k, v in new_sums.items():
                old_sums[k] = old_sums.get(k, 0) + v
            merged[bucket_key] = old_sums
        return merged
