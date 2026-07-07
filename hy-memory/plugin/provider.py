# -*- coding: utf-8 -*-
"""
HY Memory Provider for Hermes Agent — 第一梯队原生插件。

Hermes 在每次 LLM 调用前自动 `prefetch(query)`，本 Provider：
  1. 用 query 搜 HY Memory（chat 链路）
  2. 返回格式化记忆文本，Hermes 注入 system prompt
  3. 用户无需任何额外操作

生命周期（Hermes 调用顺序）：
  is_available()  → initialize(session_id)  → [prefetch / sync_turn 反复]
  → [on_pre_compress / on_session_end]  → shutdown()

Tools（LLM 主动调用，可选）：
  memory_search / memory_add / memory_delete / memory_list

Refer: https://hermesagent.org.cn/docs/developer-guide/memory-provider-plugin
"""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hermes-hy-memory")


def _configure_logger() -> None:
    """Opt-in console logging via HY_MEMORY_LOG_LEVEL.

    The plugin's logger normally inherits whatever Hermes configures for the
    root logger — which defaults to WARNING and may have no console handler, so
    the prefetch/search/write INFO lines never surface. Setting
    HY_MEMORY_LOG_LEVEL=INFO (or DEBUG) attaches a dedicated stderr handler at
    that level and stops propagation, so you reliably see HY Memory activity
    regardless of Hermes' own logging config. Unset → behave as before
    (inherit root, no handler of our own).
    """
    raw = os.environ.get("HY_MEMORY_LOG_LEVEL", "").strip().upper()
    if not raw:
        return
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        return
    logger.setLevel(level)
    # avoid stacking duplicate handlers if initialize() runs more than once
    if not any(getattr(h, "_hy_memory", False) for h in logger.handlers):
        handler = logging.StreamHandler()  # stderr
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        handler._hy_memory = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False  # don't double-emit through root


_configure_logger()


# Hermes 把 MemoryProvider ABC 暴露在 agent.memory_provider 里。
# 我们 try-import 做显式继承，让 Hermes runtime 的 isinstance() 检查能过；
# 装不到时（开发/测试阶段没装 hermes）回落到一个占位 base，逻辑跟正常一致。
try:
    from agent.memory_provider import MemoryProvider as _HermesMemoryProvider  # type: ignore
except Exception:
    class _HermesMemoryProvider:  # type: ignore[no-redef]
        """Fallback base when hermes is not installed (test / standalone use)."""
        pass


# Hermes 注入到 system prompt 的最大字符数（防止 prefetch 一次性塞太多）
_MAX_PREFETCH_CHARS = int(os.environ.get("HY_MEMORY_PREFETCH_MAX_CHARS", "2000"))

# sync_turn 后台线程池大小（同时允许的写入 in-flight 数）
_SYNC_WORKERS = int(os.environ.get("HY_MEMORY_SYNC_WORKERS", "2"))

# shutdown 等待 in-flight sync_turn 完成的最长秒数
_SHUTDOWN_GRACE_SEC = float(os.environ.get("HY_MEMORY_SHUTDOWN_GRACE_SEC", "10"))

# 写入节流：每累计 N 轮对话才落一次库（一次 add 批量提取，省 token + 防重复）。
# 默认 5（对齐 OpenClaw 的 memoryWriteTurnWindow）。设 1 即每轮都写（旧行为）。
# 不足 N 轮的尾部在 on_session_end / on_pre_compress / shutdown 时兜底 flush。
_WRITE_TURN_WINDOW = max(1, int(os.environ.get("HY_MEMORY_WRITE_TURN_WINDOW", "5") or "5"))

# Layer 值（小写 — 与 hy_memory.models.memory.MemoryLayer 的 .value 一致）
_PROFILE_LAYERS = {"l0_basic_info", "l4_identity"}
_INTENT_LAYERS = {"l7_intention"}

# 跳过的简短确认 query（不去搜记忆）
_SKIP_QUERIES = {
    "ok", "好", "好的", "thanks", "谢谢", "y", "n", "yes", "no",
    "继续", "go", "嗯", "嗯嗯", "对", "对的",
}


class HyMemoryProvider(_HermesMemoryProvider):
    """
    Hermes Memory Provider — 100% 被动注入实现。

    继承 agent.memory_provider.MemoryProvider（如果 hermes 可 import）。

    线程安全说明：
      - sync_turn 走线程池，多 turn 并发时各自独立提交
      - on_session_end / shutdown 等所有 in-flight 完成
      - HyMemoryClient 内部用 _LoopThread 跑 async，对线程池调用是安全的
    """

    def __init__(self):
        self._client = None
        self._user_id: str = ""
        self._agent_id: str = ""
        self._session_id: str = ""
        self._mode: str = "pro"
        self._initialized: bool = False
        self._lock = threading.Lock()  # 守护 _initialized + _client
        self._executor: Optional[ThreadPoolExecutor] = None
        self._inflight: List[Future] = []
        # 写入节流：每 session 缓冲未达窗口的对话轮，凑满 _WRITE_TURN_WINDOW
        # 再一次性 add。_turn_buffer[session_id] = List[{"role","content"}]。
        self._write_turn_window: int = _WRITE_TURN_WINDOW
        self._turn_buffer: Dict[str, List[Dict[str, str]]] = {}
        self._buffer_lock = threading.Lock()  # 守护 _turn_buffer

    # ================================================================
    # Properties
    # ================================================================

    @property
    def name(self) -> str:
        return "hy-memory"

    # ================================================================
    # Lifecycle
    # ================================================================

    def is_available(self) -> bool:
        """
        激活检查（不做网络请求）。

        条件：HY_MEMORY_USER_ID 已设置。其他环境（OPENAI_API_KEY 等）
        在 initialize 阶段 lazy 检查，缺失时打 error 但不抛。
        """
        return bool(os.environ.get("HY_MEMORY_USER_ID"))

    def initialize(self, session_id: str, **kwargs) -> None:
        """
        初始化 Provider — Hermes 在会话开始时调用。

        Args:
            session_id: Hermes 当前 session ID（作为 HY Memory 三级 key）
            **kwargs:   Hermes 可能传入 `hermes_home` 等，目前不使用

        失败时 self._client = None，后续所有 hook 走空操作分支，不抛错。
        """
        with self._lock:
            if self._initialized:
                return

            # Re-check log config: Hermes loads ~/.hermes/.env before initialize,
            # so HY_MEMORY_LOG_LEVEL may only be visible now.
            _configure_logger()

            self._session_id = session_id or "default_session"
            self._user_id = os.environ.get("HY_MEMORY_USER_ID", "").strip()
            self._agent_id = os.environ.get("HY_MEMORY_AGENT_ID", "hermes").strip() or "hermes"
            self._mode = os.environ.get("HY_MEMORY_MODE", "pro").strip() or "pro"
            # 写入窗口：initialize 时再读一次 env（此时 Hermes 已加载 .env）
            try:
                self._write_turn_window = max(
                    1, int(os.environ.get("HY_MEMORY_WRITE_TURN_WINDOW", "5") or "5")
                )
            except ValueError:
                self._write_turn_window = _WRITE_TURN_WINDOW

            if not self._user_id:
                logger.error("[hermes] HY_MEMORY_USER_ID not set; provider disabled")
                self._initialized = True  # 标记完成，但 _client 仍为 None
                return

            try:
                from . import home as H
                from . import server_manager as SM

                H.apply_memory_data_dir()
                vs = os.environ.get("MEMORY_VECTOR_STORE", "")

                # Reuse an existing HY Memory HTTP server when healthy (OpenClaw /
                # OpenCode / prior Hermes session). Only spawn when auto-start is
                # allowed and nothing is listening.
                auto_start = os.environ.get("HY_MEMORY_AUTO_START_SERVER", "true").lower() not in (
                    "0", "false", "no",
                )
                ok, server_url = SM.ensure_server(
                    auto_start=auto_start,
                    vector_provider=vs,
                )
                if ok:
                    from .http_client import HttpMemoryClient
                    self._client = HttpMemoryClient(server_url)
                    logger.info(f"[hermes] using HTTP server at {server_url}")
                else:
                    from hy_memory import HyMemoryClient
                    if "MEMORY_LOG_PROPAGATE" not in os.environ:
                        os.environ["MEMORY_LOG_PROPAGATE"] = "true"
                    self._client = HyMemoryClient(mode=self._mode)
                    logger.info("[hermes] using embedded HyMemoryClient (no HTTP server)")
            except ImportError as e:
                logger.error(
                    f"[hermes] hy-memory SDK not installed: {e}; "
                    f"run `pip install hy-memory`"
                )
                self._initialized = True
                return
            except Exception as e:
                # OPENAI_API_KEY missing / VDB connect failed / etc.
                logger.error(f"[hermes] HyMemoryClient init failed: {e}", exc_info=True)
                self._initialized = True
                return

            # sync_turn 用的线程池
            self._executor = ThreadPoolExecutor(
                max_workers=_SYNC_WORKERS,
                thread_name_prefix="hy-memory-sync",
            )
            self._initialized = True
            logger.info(
                f"[hermes] Provider ready: user={self._user_id} "
                f"agent={self._agent_id} session={self._session_id} mode={self._mode}"
            )

    # ================================================================
    # Configuration (setup wizard)
    # ================================================================

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "user_id",
                "label": "User ID",
                "description": "Your unique memory namespace identifier",
                "env_var": "HY_MEMORY_USER_ID",
                "required": True,
                "secret": False,
            },
            {
                "key": "agent_id",
                "label": "Agent ID",
                "description": "Agent identifier for memory isolation",
                "env_var": "HY_MEMORY_AGENT_ID",
                "required": False,
                "secret": False,
                "default": "hermes",
            },
            {
                "key": "mode",
                "label": "Processing Mode",
                "description": "lite (fast, embed-only) / pro (LLM extraction) / ultra (pro + Graph)",
                "env_var": "HY_MEMORY_MODE",
                "required": False,
                "secret": False,
                "default": "pro",
                "choices": ["lite", "pro", "ultra"],
            },
        ]

    def save_config(self, values: Dict[str, str], hermes_home: str) -> None:
        """
        把字段写到 hermes_home/.env（标准 dotenv 格式）。

        Hermes 后续会把这个 .env 加载进环境变量。
        """
        env_file = os.path.join(hermes_home, ".env")
        env_lines: List[str] = []
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        env_map = {
            "user_id": "HY_MEMORY_USER_ID",
            "agent_id": "HY_MEMORY_AGENT_ID",
            "mode": "HY_MEMORY_MODE",
        }

        for key, env_var in env_map.items():
            val = values.get(key, "")
            if val:
                env_lines = [
                    line for line in env_lines
                    if not line.strip().startswith(f"{env_var}=")
                ]
                env_lines.append(f"{env_var}={val}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(env_lines)
        logger.info(f"[hermes] Config saved to {env_file}")

    # ================================================================
    # Context Retrieval (核心 — 被动注入)
    # ================================================================

    def prefetch(self, query: str, **kwargs) -> str:
        """
        每次 LLM 调用前 — Hermes 传入用户消息，本 Provider 返回注入文本。

        失败一律返回空串（不阻塞会话）。
        Hermes 文档允许返回 str | None；本实现统一用 ""，行为等价。
        """
        if not self._client or not query:
            return ""

        q = query.strip()
        if len(q) < 3 or q.lower() in _SKIP_QUERIES:
            return ""

        try:
            result = self._client.search(
                q,
                user_ids=[self._user_id],
                agent_ids=[self._agent_id],
                limit=10,
            )
            memories = self._flatten_memories(result.get("memories"))
            logger.info(
                f"[hermes] prefetch/search: query='{q[:60]}' "
                f"hits={len(memories)} (user={self._user_id} agent={self._agent_id})"
            )
            if not memories:
                return ""

            block = self._format_memories_for_prompt(memories)
            # 把真正注入 system prompt 的整块文本打成 INFO —— Hermes 的 agent.log
            # 默认只收 INFO+（DEBUG 进不去文件），所以用 INFO 才能在
            # `hermes logs` 里看到注入了哪些记忆给 LLM。排查完可关掉。
            logger.info(
                "[hermes] prefetch inject block (%d chars):\n%s",
                len(block), block,
            )
            return block
        except Exception as e:
            logger.warning(f"[hermes] prefetch failed: {e}")
            return ""

    def queue_prefetch(self, query: str, **kwargs) -> None:
        """对话轮次后预热下一轮缓存（当前 no-op；HyMemoryClient 自身已有 cache）。"""
        return

    def system_prompt_block(self) -> str:
        return (
            "You have access to HY Memory — a persistent memory system that "
            "remembers user preferences, facts, and context across sessions. "
            "Relevant memories are automatically provided before each response."
        )

    @staticmethod
    def _flatten_memories(memories: Any) -> List[Dict[str, Any]]:
        """把 search() 的返回统一拍平成 List[dict]。

        SDK search() 在 chat 路径返回按通道分组的 dict
        ``{'profile': [...], 'proactive': [...], 'normal': [...]}``；
        旧契约/兜底可能是扁平 list。三路 layer 互斥
        （profile=l0/l6, proactive=l7, normal=其余），无需去重；
        顺序 profile→proactive→normal 与 _format_memories_for_prompt 的
        截断配合，让用户画像优先注入。
        """
        if isinstance(memories, dict):
            out: List[Dict[str, Any]] = []
            for ch in ("profile", "proactive", "normal"):
                out.extend(memories.get(ch) or [])
            return out
        return memories or []

    @staticmethod
    def _fmt_time(ts: Any) -> str:
        """unix 秒 → 'YYYY-MM-DD HH:MM'（与 OpenClaw formatTime 对齐）；无效返回 ''。"""
        try:
            if ts is None:
                return ""
            import datetime as _dt
            d = _dt.datetime.fromtimestamp(int(ts))
            return d.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    @classmethod
    def _format_memories_for_prompt(cls, memories: List[Dict[str, Any]]) -> str:
        """把搜索结果格式化为 system prompt 块 —— 对齐 OpenClaw 的格式。

        规则（与 plugins/openclaw/index.ts 的 memoryContext 一致）：
          - 整块包在 <relevant-memories>…</relevant-memories> 里，带说明头。
          - 普通记忆：`- [N] <time>  <content>`
          - 演化链（evolution_chain 长度>1，latest→oldest 排序）展开为
            oldest→newest：
              - [N] [Evolved, K versions]
                [v1] <time>  <oldest content>
                ...
                [Latest] <time>  <newest content>
          - 时间格式 YYYY-MM-DD HH:MM；缺失则省略。

        总长度截断到 _MAX_PREFETCH_CHARS，避免一次性灌爆 system prompt。
        """
        items: List[str] = []
        running = 0
        idx = 0
        for mem in memories:
            chain = mem.get("evolution_chain")
            if chain and isinstance(chain, list) and len(chain) > 1:
                # 演化链：chain[0] 最新，chain[-1] 最旧；按 旧→新 展开
                lines: List[str] = []
                for i in range(len(chain) - 1, 0, -1):
                    c = chain[i] or {}
                    when = cls._fmt_time(c.get("memory_at"))
                    lines.append(
                        f"  [v{len(chain) - i}] {when + '  ' if when else ''}{(c.get('content') or '').strip()}"
                    )
                head = chain[0] or {}
                head_when = cls._fmt_time(head.get("memory_at"))
                head_content = (head.get("content") or mem.get("content") or "").strip()
                lines.append(f"  [Latest] {head_when + '  ' if head_when else ''}{head_content}")
                entry = f"- [{idx + 1}] [Evolved, {len(chain)} versions]\n" + "\n".join(lines)
            else:
                content = (mem.get("content") or "").strip()
                if not content:
                    continue
                when = cls._fmt_time(mem.get("memory_at"))
                entry = f"- [{idx + 1}] {when + '  ' if when else ''}{content}"

            # 单条过长时截断，避免极端长 memory 吃光整块
            if len(entry) > 800:
                entry = entry[:800].rstrip() + "..."
            if running + len(entry) > _MAX_PREFETCH_CHARS:
                break
            items.append(entry)
            running += len(entry) + 1  # +1 是换行
            idx += 1

        if not items:
            return ""
        body = "\n".join(items)
        return (
            "<relevant-memories>\n"
            "The following are stored memories for the current user. Use them to "
            "personalize your response. Memories with evolution chains are expanded "
            "from oldest to newest:\n"
            f"{body}\n"
            "</relevant-memories>"
        )

    # ================================================================
    # Turn Synchronization (异步写入)
    # ================================================================

    def sync_turn(self, user_message: str, assistant_response: str, **kwargs) -> None:
        """
        每轮对话后调用 — 把 (user_message, assistant_response) 攒进 session 缓冲。

        写入节流（对齐 OpenClaw memoryWriteTurnWindow）：
          - 每轮把这对消息 append 到 _turn_buffer[session]；
          - 凑满 _write_turn_window 轮才异步 flush 一次（一次 add 批量提取，
            省 token、避免逐轮重复抽取）；
          - 不足窗口的尾部留到 on_session_end / on_pre_compress / shutdown flush。

        非阻塞：达窗口时提交给 self._executor，立即返回。
        参数名跟 Hermes 官方文档对齐（user_message / assistant_response），
        允许 Hermes 用 kwargs 调用。
        """
        if not self._client or not self._executor or not user_message:
            return

        # session_id 允许 Hermes 按 kwarg 传不同会话；缺省回落到 initialize 时的值
        session_id = (kwargs.get("session_id") or self._session_id or "default_session")

        with self._buffer_lock:
            buf = self._turn_buffer.setdefault(session_id, [])
            buf.append({"role": "user", "content": user_message})
            buf.append({"role": "assistant", "content": assistant_response or ""})
            # 缓冲里的“轮数” = user 消息数
            turns = sum(1 for m in buf if m["role"] == "user")
            if turns < self._write_turn_window:
                logger.info(
                    f"[hermes] sync_turn buffered: {turns}/{self._write_turn_window} "
                    f"turns (session={session_id}) — not writing yet"
                )
                return  # 还没攒够，先不写
            # 达到窗口：取走整批，清空缓冲，异步落库
            batch = buf[:]
            self._turn_buffer[session_id] = []

        logger.info(
            f"[hermes] sync_turn flush: {turns} turns → write "
            f"(session={session_id} user={self._user_id} agent={self._agent_id})"
        )
        self._submit_write(batch, session_id)

    def _submit_write(self, messages: List[Dict[str, str]], session_id: str) -> None:
        """把一批消息提交线程池异步 add；记录 future 到 _inflight。"""
        if not messages:
            return
        try:
            fut = self._executor.submit(self._do_sync_turn, messages, session_id)
        except RuntimeError:
            # executor 已关闭（典型场景：shutdown 后被调用）
            logger.debug("[hermes] write skipped: executor already shut down")
            return

        self._inflight.append(fut)
        # 回收已完成的 future 引用，避免列表越来越长
        self._inflight = [f for f in self._inflight if not f.done()]

    def _flush_session_buffer(self, session_id: Optional[str] = None) -> None:
        """把缓冲里不足窗口的尾部提交落库。

        session_id=None 时 flush 所有 session（shutdown 用）。
        """
        with self._buffer_lock:
            if session_id is None:
                pending = [(sid, msgs[:]) for sid, msgs in self._turn_buffer.items() if msgs]
                self._turn_buffer.clear()
            else:
                msgs = self._turn_buffer.get(session_id) or []
                pending = [(session_id, msgs[:])] if msgs else []
                if session_id in self._turn_buffer:
                    self._turn_buffer[session_id] = []
        for sid, msgs in pending:
            self._submit_write(msgs, sid)

    def _do_sync_turn(self, messages: List[Dict[str, str]], session_id: str) -> None:
        """实际的 add 调用，跑在线程池里。messages 已是 role/content 列表。"""
        try:
            result = self._client.add(
                messages,
                user_id=self._user_id,
                agent_id=self._agent_id,
                session_id=session_id,
            )
            ok = bool(result.get("success")) if isinstance(result, dict) else True
            logger.info(
                f"[hermes] write {'ok' if ok else 'returned failure'}: "
                f"n={len(messages)} msgs (session={session_id})"
            )
        except Exception as e:
            logger.warning(f"[hermes] sync_turn failed: {e}")

    # ================================================================
    # Session End / Pre-compress
    # ================================================================

    def on_session_end(self, messages: List[Dict[str, str]], **kwargs) -> None:
        """
        会话结束时调用 — flush 缓冲里不足窗口的尾部，再等 in-flight 写完。

        节流模式下尾部可能攒了 1..N-1 轮还没落库，这里兜底 flush，保证
        会话内容不丢。flush 用的是 sync_turn 攒下的 buffer（精确、无重复），
        不再对 messages[-6:] 做二次提取（会与 buffer 重复写）。
        """
        if not self._client:
            return

        session_id = kwargs.get("session_id")
        self._flush_session_buffer(session_id)
        self._wait_inflight(_SHUTDOWN_GRACE_SEC)

    def on_pre_compress(self, messages: List[Dict[str, str]], **kwargs) -> None:
        """上下文压缩前 — 跟 on_session_end 一致，把即将被裁的内容入库。"""
        self.on_session_end(messages)

    def on_memory_write(self, action: str, target: str, content: str, **kwargs) -> None:
        """
        Hermes 内置 memory 命令变更时同步到 HY Memory。

        - action="add":    add(content)
        - action="delete": 我们没有 Hermes target ID 到 HY Memory ID 的映射，跳过
        """
        if not self._client or not content:
            return

        if action == "delete":
            logger.debug(f"[hermes] on_memory_write delete ignored target={target}")
            return

        try:
            self._client.add(
                content,
                user_id=self._user_id,
                agent_id=self._agent_id,
                session_id=self._session_id,
            )
            logger.debug(f"[hermes] on_memory_write add: '{content[:50]}...'")
        except Exception as e:
            logger.warning(f"[hermes] on_memory_write failed: {e}")

    # ================================================================
    # Tools (LLM 主动调用入口)
    # ================================================================

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "memory_search",
                "description": (
                    "Search stored memories for relevant context. "
                    "Use to find specific remembered facts or preferences."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Max results (default: 10)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memory_add",
                "description": (
                    "Store a new memory. Use to save important facts, "
                    "preferences, or decisions for future reference."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Memory content to store"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "memory_delete",
                "description": "Delete a specific memory by its memory_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Memory ID to delete"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "memory_list",
                "description": "List stored memories for the current user/agent.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Max results (default: 20)"},
                    },
                },
            },
        ]

    def handle_tool_call(self, name: str, args: Dict[str, Any]) -> str:
        """Dispatch an LLM tool call and return a **string** result.

        Hermes places this return value directly into the tool-result message's
        ``content`` field. The OpenAI-compatible chat APIs (DeepSeek, etc.)
        require ``content`` to be a string or a list — a raw dict triggers
        ``HTTP 400: content should be a string or a list``. All bundled Hermes
        memory providers annotate ``handle_tool_call(...) -> str`` for the same
        reason, so we JSON-encode the structured result here.
        """
        return json.dumps(self._dispatch_tool(name, args), ensure_ascii=False)

    def _dispatch_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Internal dispatch — returns the structured dict (JSON-encoded by caller)."""
        if not self._client:
            return {"error": "Provider not initialized"}

        try:
            if name == "memory_search":
                return self._tool_search(args)
            if name == "memory_add":
                return self._tool_add(args)
            if name == "memory_delete":
                return self._tool_delete(args)
            if name == "memory_list":
                return self._tool_list(args)
            return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"[hermes] tool {name} failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _tool_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query", "")
        limit = int(args.get("limit") or 10)
        result = self._client.search(
            query,
            user_ids=[self._user_id],
            agent_ids=[self._agent_id],
            limit=limit,
        )
        memories = self._flatten_memories(result.get("memories"))
        return {
            "status": "success",
            "count": len(memories),
            "memories": [
                {
                    "memory_id": m.get("memory_id", ""),
                    "content": m.get("content", ""),
                    "layer": m.get("layer", ""),
                    "score": m.get("score", 0),
                }
                for m in memories
            ],
        }

    def _tool_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        content = args.get("content", "")
        if not content:
            return {"error": "content is required"}
        result = self._client.add(
            content,
            user_id=self._user_id,
            agent_id=self._agent_id,
            session_id=self._session_id,
        )
        return {
            "status": "success" if result.get("success") else "error",
            "memory_id": result.get("memory_id", ""),
        }

    def _tool_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        memory_id = args.get("memory_id", "")
        if not memory_id:
            return {"error": "memory_id is required"}
        result = self._client.delete(memory_id)
        return {
            "status": "success" if result.get("success") else "error",
            "deleted_count": result.get("deleted_count", 0),
        }

    def _tool_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        limit = int(args.get("limit") or 20)
        result = self._client.list_memories(
            user_id=self._user_id,
            agent_id=self._agent_id,
            limit=limit,
        )
        # list_memories 真实返回是 {"vdb": {"memories": [...], "total": ...}, ...}
        vdb_bucket = result.get("vdb") or {}
        memories = vdb_bucket.get("memories") or []
        return {
            "status": "success",
            "count": len(memories),
            "total": vdb_bucket.get("total", 0),
            "memories": [
                {
                    "memory_id": m.get("memory_id", ""),
                    "content": m.get("content", ""),
                    "layer": m.get("layer", ""),
                }
                for m in memories
            ],
        }

    # ================================================================
    # Shutdown
    # ================================================================

    def shutdown(self) -> None:
        """关闭 — flush 所有 session 缓冲，等 in-flight 写完，再关 client + executor。"""
        with self._lock:
            # 先把所有 session 尾部缓冲提交（不丢未达窗口的对话）
            self._flush_session_buffer(None)
            self._wait_inflight(_SHUTDOWN_GRACE_SEC)

            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=True, cancel_futures=False)
                except Exception:
                    pass
                self._executor = None

            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

            self._initialized = False
            logger.info("[hermes] Provider shutdown")

    def _wait_inflight(self, timeout_sec: float) -> None:
        """等所有 in-flight sync_turn 完成（timeout 后放弃，不阻塞主流程）。"""
        if not self._inflight:
            return
        pending = [f for f in self._inflight if not f.done()]
        if not pending:
            return
        per_each = max(0.1, timeout_sec / len(pending))
        for f in pending:
            try:
                f.result(timeout=per_each)
            except Exception:
                pass
        self._inflight.clear()


# ================================================================
# Plugin Entry Point
# ================================================================

def register(ctx) -> None:
    """
    Hermes 插件注册入口。

    Hermes 发现插件后调用此函数，传入注册上下文 ctx，
    我们用 ctx.register_memory_provider 把 Provider 实例注册进去。
    """
    ctx.register_memory_provider(HyMemoryProvider())
