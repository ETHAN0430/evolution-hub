# -*- coding: utf-8 -*-
"""
Coding Memory - Scene Judge

两个职责（同模块、共用 LLMConfig.model）：

1. classify_messages_is_coding(messages, llm)
   写入端：对整段 messages 做单一二分判定（is_coding ∈ {True, False}）
   不切 segment、不分 turn —— 整段一条链路。

2. classify_queries_is_coding(queries, llm)
   搜索端：以 queries 中末尾为目标 query，前置 queries 作为上下文，判定 is_coding。

详见 docs/coding_memory_mvp_design.md §6.3 / §8.3。
"""

import json
import logging
from typing import List, Optional, Dict, Any

from ..agent.llm_provider import LLMProvider
from ..pipelines.base import ChatMessage
from .preproc import extract_tool_summary

logger = logging.getLogger(__name__)


def _resolve_llm_temperature(llm_provider: LLMProvider, default: float = 0.1) -> float:
    """
    从 MemoryConfig.llm.temperature 解析温度（与 MemAgent 路径一致）。

    LLMProvider._llm_config 是 agent 内部 LLMConfig，历史上不含 temperature；
    优先读 config.llm.temperature，避免 fallback 到 0.1 触发 kimi 等平台硬约束。
    """
    config = getattr(llm_provider, "config", None)
    if config is not None:
        llm = getattr(config, "llm", None)
        temp = getattr(llm, "temperature", None) if llm is not None else None
        if temp is not None:
            return float(temp)
    inner = getattr(llm_provider, "_llm_config", None)
    temp = getattr(inner, "temperature", None) if inner is not None else None
    if temp is not None:
        return float(temp)
    return float(default)


# ================================================================
# 写入端：整段二分类
# ================================================================

CLASSIFY_MESSAGES_PROMPT = """\
You are a single-label scene classifier. Decide the DOMINANT scene of the entire
conversation chunk passed to you.

Output exactly one of:
  "coding"  ← user is primarily doing engineering work (code/files/commands/
              deploy/debug). Tool calls are doing real work, and instructions/
              conventions/decisions/learnings may emerge.
  "chat"    ← user is primarily having casual conversation, sharing personal
              info, asking factual Q&A unrelated to dev/ops. Tool calls (if any)
              are incidental.

Rules:
- Look at the WHOLE chunk, not individual turns. A few stray off-topic turns
  inside a clearly engineering chunk should still be "coding".
- A few stray tool calls inside a clearly chat chunk should still be "chat".
- When in doubt, prefer "chat" (we'd rather miss a coding extraction than
  pollute coding memory with chat content).

Conversation summary (turns with user query + tool names used):
{turns_block}

Output strict JSON only, no markdown:
{{"is_coding": true/false, "reason": "..."}}
"""


async def classify_messages_is_coding(
    messages: List[ChatMessage],
    llm_provider: LLMProvider,
    *,
    max_tokens: int = 200,
    temperature: Optional[float] = None,
) -> bool:
    """
    对整段 messages 做单一 is_coding 判定。

    复用 LLMConfig.model（不引入独立 classifier 配置）。
    temperature=None 时使用 config.llm.temperature（与 MemAgent 路径一致），
    避免硬编码 0.0 触发 kimi/deepseek 等模型的温度硬约束。
    fail-safe：LLM 调用失败或解析失败，返回 False（fallback 走 chat 链）。
    """
    if not messages:
        return False

    summary = extract_tool_summary(messages)
    turns_block = _format_turns(summary)
    prompt = CLASSIFY_MESSAGES_PROMPT.format(turns_block=turns_block)

    if temperature is None:
        temperature = _resolve_llm_temperature(llm_provider)

    try:
        resp = await llm_provider.complete(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result = _parse_is_coding_json(resp.content)
        if result is None:
            logger.warning(
                f"[coding-judge] failed to parse classify_messages output: {resp.content!r}; defaulting to chat"
            )
            return False
        is_coding = bool(result.get("is_coding", False))
        logger.info(
            f"[coding-judge] is_coding={is_coding} reason={result.get('reason', '')!r}"
        )
        return is_coding
    except Exception as e:
        logger.warning(f"[coding-judge] classify_messages LLM failed: {e}; defaulting to chat")
        return False


# ================================================================
# 搜索端：用 queries 上下文判类
# ================================================================

CLASSIFY_QUERIES_PROMPT = """\
Classify the LATEST query as either "coding" or "chat".
Use the earlier queries (if any) as context for disambiguation.

coding = looking for past engineering / dev / ops solutions:
  how-to-do-X, what-was-the-decision, where-are-credentials,
  why-did-we-choose-Y, debug-this-error, configure-Z.

chat = casual conversation, personal info, factual Q&A unrelated to dev.

Recent queries (oldest → newest, last is target):
{queries_block}

Output strict JSON only, no markdown:
{{"is_coding": true/false}}
"""


async def classify_queries_is_coding(
    queries: List[str],
    llm_provider: LLMProvider,
    *,
    max_tokens: int = 100,
    temperature: Optional[float] = None,
) -> bool:
    """
    对一组 queries（末尾为目标）判类。

    单 query 输入也支持（前置上下文为空）。
    temperature=None 时使用 config.llm.temperature。
    fail-safe：LLM 调用失败或解析失败，返回 False（走现有 chat 召回）。
    """
    if not queries:
        return False

    queries_block = "\n".join(
        f"{i + 1}. {repr(q)}" + ("   ← target" if i == len(queries) - 1 else "")
        for i, q in enumerate(queries)
    )
    prompt = CLASSIFY_QUERIES_PROMPT.format(queries_block=queries_block)

    if temperature is None:
        temperature = _resolve_llm_temperature(llm_provider)

    try:
        resp = await llm_provider.complete(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result = _parse_is_coding_json(resp.content)
        if result is None:
            logger.warning(
                f"[coding-judge] failed to parse classify_queries output: {resp.content!r}; defaulting to chat"
            )
            return False
        is_coding = bool(result.get("is_coding", False))
        logger.info(f"[coding-judge] queries is_coding={is_coding}")
        return is_coding
    except Exception as e:
        logger.warning(f"[coding-judge] classify_queries LLM failed: {e}; defaulting to chat")
        return False


# ================================================================
# 搜索端：极简判类 + 改写（单次 LLM，搜索路径必须低时延）
# ================================================================

CLASSIFY_AND_REWRITE_PROMPT = """\
Task: Given queries (oldest -> newest, last is target), do TWO things:
1) Classify the target as 0 (chat / non-coding) or 1 (coding / engineering/dev/ops question).
2) Rewrite the target into ONE concise standalone query, expanding pronouns / restoring
   omitted context using the earlier queries. Keep the same language.

Output STRICTLY in this format, nothing else:
<0 or 1>
<rewritten query>

Queries:
{queries_block}
"""


async def classify_and_rewrite_queries(
    queries: List[str],
    llm_provider: LLMProvider,
    *,
    max_tokens: int = 200,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    """
    单次 LLM 调用同时做：
    1) 判定 target query (queries[-1]) 是 coding(1) / chat(0)
    2) 用前置 queries 上下文做改写（消除指代 / 补全省略），返回 rewrite_query

    输出格式刻意保持极简（避免 JSON 解析开销 + 让 LLM 输出短）：
        第一行: 0 或 1
        第二行: rewritten query

    Returns:
        {"is_coding": bool, "rewrite_query": str, "ok": bool}
        失败时 ok=False，is_coding 默认 False，rewrite_query 等于 queries[-1]

    fail-safe：LLM 失败 / 解析失败一律 ok=False（caller 应回退默认 chat 路径）。
    """
    target = queries[-1] if queries else ""
    fallback = {"is_coding": False, "rewrite_query": target, "ok": False}
    if not queries:
        return fallback

    queries_block = "\n".join(
        f"- {q}" + ("   <-- target" if i == len(queries) - 1 else "")
        for i, q in enumerate(queries)
    )
    prompt = CLASSIFY_AND_REWRITE_PROMPT.format(queries_block=queries_block)

    if temperature is None:
        temperature = _resolve_llm_temperature(llm_provider)

    try:
        resp = await llm_provider.complete(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        logger.warning(f"[coding-judge] classify_and_rewrite LLM failed: {e}; falling back to chat")
        return fallback

    text = (resp.content or "").strip()
    if not text:
        logger.warning("[coding-judge] classify_and_rewrite empty content; falling back to chat")
        return fallback

    # 去 markdown fence（保险）
    if text.startswith("```"):
        lines = text.split("\n")
        body = []
        in_fence = False
        for line in lines:
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            body.append(line)
        text = "\n".join(body).strip() or text

    # 拆解：第一行 = 0/1，剩下的 = rewrite
    lines = text.split("\n", 1)
    head = lines[0].strip().rstrip(",.").rstrip("。，")
    rewrite = (lines[1].strip() if len(lines) > 1 else "").strip()
    if not rewrite:
        rewrite = target  # 没改写就用原 target

    # 容错：LLM 可能输出 "0/1" 周围带空格、引号、句号
    if head in ("1", "true", "True", "TRUE", "yes", "Yes", "YES", "y", "Y"):
        is_coding = True
    elif head in ("0", "false", "False", "FALSE", "no", "No", "NO", "n", "N"):
        is_coding = False
    else:
        c = head[:1] if head else ""
        if c == "1":
            is_coding = True
        elif c == "0":
            is_coding = False
        else:
            logger.warning(
                f"[coding-judge] classify_and_rewrite unrecognized head={head!r}; falling back to chat"
            )
            return {"is_coding": False, "rewrite_query": rewrite, "ok": False}

    logger.info(
        f"[coding-judge] classify_and_rewrite is_coding={is_coding} "
        f"rewrite={rewrite!r}"
    )
    return {"is_coding": is_coding, "rewrite_query": rewrite, "ok": True}


# ================================================================
# Helpers
# ================================================================

def _format_turns(summary: List[Dict[str, Any]]) -> str:
    """渲染 turn 简化视图给 LLM 看。"""
    if not summary:
        return "(empty)"
    rows = []
    for t in summary:
        user = t.get("user", "") or ""
        # 单 turn 用户文本截到 200 字符
        if len(user) > 200:
            user = user[:200] + "..."
        tools = t.get("tools", []) or []
        rows.append(
            f"- turn {t.get('turn', '?')}: user={user!r}, tools={tools}"
            + (", has_tool_result=True" if t.get("has_tool_result") else "")
        )
    return "\n".join(rows)


def _parse_is_coding_json(text: str) -> Optional[Dict[str, Any]]:
    """
    宽松解析 LLM 输出。先试纯 JSON，再试在文本里找第一个 {...} 块。
    返回 None 表示无法解析。
    """
    if not text:
        return None
    text = text.strip()
    # 去 markdown fence
    if text.startswith("```"):
        # ```json ... ```
        lines = text.split("\n")
        # 去掉首尾 fence
        body_lines = []
        in_fence = False
        for line in lines:
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not body_lines and line.startswith("```"):
                continue
            body_lines.append(line)
        text = "\n".join(body_lines).strip() or text

    # 直接 JSON
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "is_coding" in obj:
            return obj
    except Exception:
        pass

    # 找第一个 { ... } 块
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        snippet = text[start: end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict) and "is_coding" in obj:
                return obj
        except Exception:
            return None
    return None
