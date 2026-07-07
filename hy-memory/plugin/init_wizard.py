# -*- coding: utf-8 -*-
"""
HY Memory init wizard for Hermes — provider catalog + config builders + .env writer.

Mirrors the OpenClaw plugin's init wizard 1:1 (same providers, same default
models, same dimensions). The interactive flow lives in cli.py `_cmd_init`;
this module holds the pure, testable pieces.

The SDK speaks one protocol: OpenAI-compatible. Every provider therefore maps
to MEMORY_LLM_PROVIDER=openai with its own base_url (matching the OpenClaw
buildLlmConfig behavior). The wizard writes plain `KEY=value` lines into
~/.hermes/.env which the SDK reads via os.getenv.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ============================================================================
# Provider catalogs — kept identical to plugins/openclaw/cli/init-wizard.ts
# ============================================================================


@dataclass
class ProviderDef:
    id: str
    label: str
    needs_api_key: bool
    needs_url: bool
    default_model: str
    default_url: Optional[str] = None


@dataclass
class EmbedderDef(ProviderDef):
    default_dims: int = 1536


@dataclass
class VectorDef:
    id: str
    label: str
    needs_connection: bool
    default_url: Optional[str] = None
    setup_hint: Optional[str] = None


LLM_PROVIDERS: List[ProviderDef] = [
    ProviderDef("openai", "OpenAI", True, False, "gpt-5.5-instant"),
    ProviderDef("anthropic", "Anthropic", True, False, "claude-sonnet-4.6"),
    ProviderDef("google", "Google Gemini", True, False, "gemini-3.1-pro", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ProviderDef("openrouter", "OpenRouter (multi-model)", True, False, "openrouter/auto", "https://openrouter.ai/api/v1"),
    ProviderDef("deepseek", "DeepSeek", True, False, "deepseek-v4-flash", "https://api.deepseek.com"),
    ProviderDef("hunyuan", "Hy (Tencent)", True, False, "hy3-preview", "https://tokenhub.tencentmaas.com/v1"),
    ProviderDef("moonshot", "Moonshot (Kimi)", True, False, "kimi-k2.5", "https://api.moonshot.cn/v1"),
    ProviderDef("minimax", "MiniMax", True, False, "minimax-m2.1", "https://api.minimax.chat/v1"),
    ProviderDef("zhipu", "Z.ai (智谱)", True, False, "glm-4.7-flash", "https://open.bigmodel.cn/api/paas/v4"),
    ProviderDef("ollama", "Ollama (local, free)", False, True, "qwen3-7b-instruct", "http://localhost:11434/v1"),
]

EMBEDDER_PROVIDERS: List[EmbedderDef] = [
    EmbedderDef("openai", "OpenAI", True, False, "text-embedding-3-small", default_dims=768),
    EmbedderDef("gemini", "Google Gemini", True, False, "text-embedding-004", "https://generativelanguage.googleapis.com/v1beta/openai", default_dims=768),
    EmbedderDef("aliyun", "Aliyun Bailian (百炼)", True, False, "text-embedding-v4", "https://dashscope.aliyuncs.com/compatible-mode/v1", default_dims=1024),
    EmbedderDef("moonshot", "Moonshot", True, False, "moonshot-v1-embedding", "https://api.moonshot.cn/v1", default_dims=1024),
    EmbedderDef("ollama", "Ollama (local, free)", False, True, "nomic-embed-text", "http://localhost:11434/v1", default_dims=768),
]

VECTOR_PROVIDERS: List[VectorDef] = [
    VectorDef("chroma", "ChromaDB (embedded, zero setup)", False),
    VectorDef("qdrant", "Qdrant", True, "http://localhost:6333", "docker run -d -p 6333:6333 qdrant/qdrant"),
    VectorDef("faiss", "FAISS (local file)", False),
]

KNOWN_EMBEDDER_DIMS: Dict[str, int] = {
    "text-embedding-3-small": 768,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "text-embedding-004": 768,
    "text-embedding-v4": 1024,
    "moonshot-v1-embedding": 1024,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
}


# ============================================================================
# Config builders → SDK env vars
# ============================================================================


def build_llm_env(provider_id: str, *, api_key: Optional[str], model: Optional[str], url: Optional[str]) -> Dict[str, str]:
    """Return MEMORY_LLM_* env for the chosen provider.

    Every provider maps to the OpenAI-compatible path (provider=openai +
    base_url); the SDK has no dedicated anthropic branch. Thinking is disabled
    to keep memory extraction fast/cheap (same as OpenClaw).
    """
    defn = next((p for p in LLM_PROVIDERS if p.id == provider_id), None)
    if defn is None:
        raise ValueError(f"Unknown LLM provider: {provider_id}")
    env: Dict[str, str] = {
        "MEMORY_LLM_PROVIDER": "openai",
        "MEMORY_LLM_MODEL": model or defn.default_model,
        "HY_MEMORY_THINKING_MODE": "disabled",
    }
    if api_key:
        env["MEMORY_LLM_API_KEY"] = api_key
    base_url = url or defn.default_url
    if base_url:
        env["MEMORY_LLM_BASE_URL"] = base_url
    return env


def build_embedder_env(provider_id: str, *, api_key: Optional[str], model: Optional[str], url: Optional[str], dims: Optional[int]) -> Dict[str, str]:
    defn = next((p for p in EMBEDDER_PROVIDERS if p.id == provider_id), None)
    if defn is None:
        raise ValueError(f"Unknown embedder provider: {provider_id}")
    final_model = model or defn.default_model
    final_dims = dims if dims is not None else KNOWN_EMBEDDER_DIMS.get(final_model, defn.default_dims)
    env: Dict[str, str] = {
        "MEMORY_EMBEDDER_PROVIDER": "openai",
        "MEMORY_EMBEDDER_MODEL": final_model,
        "MEMORY_EMBEDDING_DIMS": str(final_dims),
    }
    if api_key:
        env["MEMORY_EMBEDDER_API_KEY"] = api_key
    base_url = url or defn.default_url
    if base_url:
        env["MEMORY_EMBEDDER_BASE_URL"] = base_url
    return env


def build_vector_env(provider_id: str, *, host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, str]:
    env: Dict[str, str] = {"MEMORY_VECTOR_STORE": provider_id}
    if provider_id == "qdrant":
        env["MEMORY_VECTOR_HOST"] = host or "localhost"
        env["MEMORY_VECTOR_PORT"] = str(port or 6333)
    return env


# ============================================================================
# .env merge / write
# ============================================================================


def merge_env_lines(existing: str, updates: Dict[str, str]) -> str:
    """Merge KEY=value updates into an existing .env text.

    - Replaces in place if KEY already present (keeps file order / comments).
    - Appends new keys at the end.
    - Returns the new file content (trailing newline guaranteed).
    """
    lines = existing.splitlines()
    remaining = dict(updates)
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")  # blank separator before appended block
        for key, val in remaining.items():
            out.append(f"{key}={val}")
    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text


def default_hermes_env_path() -> Path:
    return Path(os.path.expanduser("~")) / ".hermes" / ".env"


def default_hermes_config_path() -> Path:
    return Path(os.path.expanduser("~")) / ".hermes" / "config.yaml"


def set_memory_provider(path: Path, provider: str = "hy-memory") -> bool:
    """Set `memory.provider: <provider>` in a Hermes config.yaml.

    Memory providers are single-select, so this overwrites any existing
    memory.provider. Other keys (and, best-effort, comments) are preserved.
    Returns True if the file was written, False if it was already set.

    Requires PyYAML (a transitive dependency of the hy-memory SDK).
    """
    import yaml  # transitive via hy-memory; guaranteed present at runtime

    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    memory = data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
    if memory.get("provider") == provider:
        return False  # already active — nothing to do

    memory["provider"] = provider
    data["memory"] = memory
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True


def write_env_file(path: Path, updates: Dict[str, str]) -> None:
    """Merge updates into path (creating dirs/file as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(merge_env_lines(existing, updates), encoding="utf-8")


def default_user_id() -> str:
    try:
        import getpass
        return getpass.getuser() or "default"
    except Exception:
        return "default"
