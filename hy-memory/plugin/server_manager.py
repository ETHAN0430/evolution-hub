# -*- coding: utf-8 -*-
"""HY Memory HTTP server lifecycle for Hermes (shared ~/.hy-memory/.venv)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import home as H

DEFAULT_SERVER_PORT = 19527
SDK_PACKAGE = "hy-memory"
PYPI_INDEX_URL = os.environ.get("HY_MEMORY_PYPI_INDEX_URL", "https://pypi.org/simple")


def default_server_url(port: int = DEFAULT_SERVER_PORT) -> str:
    env = os.environ.get("HY_MEMORY_SERVER_URL", "").strip()
    if env:
        return env.rstrip("/")
    return f"http://127.0.0.1:{port}"


def health_check(url: Optional[str] = None, timeout: float = 3.0) -> bool:
    base = (url or default_server_url()).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _pip_spec(vector_provider: str = "") -> str:
    vs = (vector_provider or os.environ.get("MEMORY_VECTOR_STORE", "")).lower()
    if vs == "qdrant":
        return f"{SDK_PACKAGE}[qdrant]"
    if vs == "faiss":
        return f"{SDK_PACKAGE}[faiss]"
    return SDK_PACKAGE


def _venv_python() -> Path:
    return H.venv_python()


def venv_ready() -> bool:
    py = _venv_python()
    if not py.exists():
        return False
    out = subprocess.run(
        [str(py), "-c", "import hy_memory.server"],
        capture_output=True,
        timeout=15,
    )
    return out.returncode == 0


def _find_system_python() -> str:
    candidates = [
        "python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python3.8",
        "python3", "/usr/bin/python3", "/usr/local/bin/python3", "python",
    ]
    if os.name == "nt":
        candidates = ["python", "python3"] + candidates
    for cmd in candidates:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5, check=True)
            return cmd
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
    return "python3" if os.name != "nt" else "python"


def ensure_venv(*, vector_provider: str = "", upgrade: bool = True) -> Path:
    """Ensure managed venv exists with hy-memory SDK; return python path."""
    H.ensure_home_layout()
    venv_dir = H.VENV_DIR
    py = H.venv_python()
    pip_spec = _pip_spec(vector_provider)
    index_args = ["--index-url", PYPI_INDEX_URL]

    if not H.venv_layout_exists():
        sys_py = _find_system_python()
        subprocess.run(
            [sys_py, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        py = H.venv_python()

    if venv_ready():
        if upgrade:
            subprocess.run(
                [str(py), "-m", "pip", "install", "--quiet", "--upgrade", *index_args, pip_spec],
                capture_output=True,
                timeout=300,
            )
        return py

    subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", *index_args, pip_spec],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return py


def build_server_env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    env["MEMORY_DATA_DIR"] = str(H.DB_DIR)
    env["MEMORY_MODE"] = os.environ.get("HY_MEMORY_MODE", os.environ.get("MEMORY_MODE", "pro"))
    if env["MEMORY_MODE"] == "ultra":
        env["MEMORY_GRAPH_PROVIDER"] = "kuzu"
    env["MEMORY_ENABLE_SEARCH_QUERY"] = "false"
    env["MEMORY_CACHE_BACKEND"] = "sqlite"
    env["MEMORY_PIPELINE_TRACE_ENABLED"] = "false"
    # Fix System 2: increase agent max tokens to prevent JSON truncation
    env["MEMORY_AGENT_MAX_TOKENS"] = "16000"
    # Batch digest: 每次处理更多 fresh facts（框架类事实需要更大的池才能聚类）
    env["MEMORY_S2_BATCH_SIZE"] = "300"
    env["MEMORY_S2_CLUSTER_THRESHOLD"] = "0.55"
    # Fix Chroma collection: 强制使用 1024-dim 集合（老数据在那）
    env["MEMORY_EMBEDDING_DIMS"] = "1024"
    if not os.environ.get("MEMORY_VECTOR_STORE"):
        env["MEMORY_VECTOR_STORE"] = "chroma"
    for key in (
        "MEMORY_LLM_PROVIDER", "MEMORY_LLM_MODEL", "MEMORY_LLM_API_KEY", "MEMORY_LLM_BASE_URL",
        "MEMORY_EMBEDDER_PROVIDER", "MEMORY_EMBEDDER_MODEL", "MEMORY_EMBEDDER_API_KEY",
        "MEMORY_EMBEDDER_BASE_URL", "MEMORY_EMBEDDING_DIMS", "MEMORY_VECTOR_STORE",
        "MEMORY_VECTOR_HOST", "MEMORY_VECTOR_PORT", "MEMORY_LOG_LEVEL",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            env[key] = val
    return env


def ensure_server(
    *,
    port: int = DEFAULT_SERVER_PORT,
    auto_start: bool = True,
    vector_provider: str = "",
) -> Tuple[bool, str]:
    """Return (healthy, server_url). Reuses existing server; spawns only when needed."""
    url = default_server_url(port)
    if health_check(url):
        return True, url

    if not auto_start:
        return False, url

    py = ensure_venv(vector_provider=vector_provider, upgrade=False)
    env = {k: v for k, v in {**os.environ, **build_server_env()}.items() if k.upper() != "PYTHONPATH"}
    proc = subprocess.Popen(
        [str(py), "-m", "hy_memory.server", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if health_check(url):
            return True, url
        if proc.poll() is not None:
            break
        time.sleep(0.3)
    try:
        proc.terminate()
    except OSError:
        pass
    return health_check(url), url
