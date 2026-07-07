# -*- coding: utf-8 -*-
"""Unified HY Memory home paths (~/.hy-memory/)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

HY_MEMORY_HOME = Path(
    os.environ.get("HY_MEMORY_HOME", "").strip() or (Path.home() / ".hy-memory")
)
VENV_DIR = HY_MEMORY_HOME / ".venv"
DB_DIR = HY_MEMORY_HOME / "db"
CONFIG_JSON_PATH = HY_MEMORY_HOME / "config.json"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_layout_exists() -> bool:
    return venv_python().exists()


def ensure_home_layout() -> None:
    HY_MEMORY_HOME.mkdir(parents=True, exist_ok=True)
    DB_DIR.mkdir(parents=True, exist_ok=True)


def apply_memory_data_dir() -> Path:
    """Set MEMORY_DATA_DIR to ~/.hy-memory/db when unset."""
    if not os.environ.get("MEMORY_DATA_DIR", "").strip():
        os.environ["MEMORY_DATA_DIR"] = str(DB_DIR)
    return Path(os.environ["MEMORY_DATA_DIR"])


def write_config_snapshot(plugin: Dict[str, Any], source: str) -> None:
    ensure_home_layout()
    payload = {
        "updatedAt": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "source": source,
        "plugin": plugin,
    }
    CONFIG_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
