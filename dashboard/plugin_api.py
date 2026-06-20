"""
hermes-evolution-hub Dashboard plugin backend API.
Mounted at /api/plugins/hermes-evolution-hub/ by Hermes Dashboard (9119).
No separate HTTP server needed.
"""
import asyncio
import functools
import json
import os
import re
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["evolution-hub"])

# ── paths ──────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent.parent  # ~/.hermes/plugins/evolution-hub/
_EVOLUTION_DIR = _HERE / "evolution_hub"
_AGENT_LOG = Path.home() / ".hermes" / "logs" / "agent.log"
_CONFIG_YAML = Path.home() / ".hermes" / "config.yaml"
_CACHE_DB = Path.home() / ".hy_memory" / "data" / "cache.db"

# ── simple TTL cache ──────────────────────────────────────────────────────
_cache: Dict[str, dict] = {}


def cached(ttl: float = 5):
    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            key = fn.__name__
            now = datetime.now().timestamp()
            if key in _cache and now - _cache[key]["ts"] < ttl:
                return _cache[key]["data"]
            data = fn(*args, **kwargs)
            _cache[key] = {"data": data, "ts": now}
            return data
        return wrapped
    return deco


# ── helpers ────────────────────────────────────────────────────────────────
def _query_db(sql: str, params: tuple = ()):
    try:
        conn = sqlite3.connect(str(_CACHE_DB), timeout=5)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


# ── API endpoints ─────────────────────────────────────────────────────────

@router.get("/api/health")
async def api_health():
    """Health: VDB / embed / LLM status + prefetch stats + pipeline activity."""
    data: Dict[str, Any] = {}

    # 1. HY Memory server check
    try:
        req = urllib.request.Request("http://localhost:19527/api/v1/status")
        resp = urllib.request.urlopen(req, timeout=3)
        s = json.loads(resp.read())
        data["server"] = {
            "vdb": s.get("vdb"),
            "embed": str(s.get("embed", "?"))[:20],
            "llm": str(s.get("llm", "?"))[:20],
            "vdb_points": s.get("vdb_points", 0),
        }
    except Exception:
        data["server"] = {"vdb": "down", "embed": "down", "llm": "down", "vdb_points": 0}

    # 2. Prefetch stats from agent.log
    try:
        r = subprocess.run(
            ["grep", "-E", "prefetch", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        recent = r.stdout.strip().split("\n")[-30:]
        data["prefetch"] = {
            "ok": sum(1 for l in recent if "hits=" in l),
            "fail": sum(1 for l in recent if "failed" in l),
        }
    except Exception:
        data["prefetch"] = {"ok": 0, "fail": 0}

    # 3. Pipeline activity (last hour)
    rows = _query_db(
        "SELECT step, count(*) FROM pipeline_logs "
        "WHERE created_at > datetime('now','-1 hour') GROUP BY step"
    )
    data["pipeline_1h"] = {r[0]: r[1] for r in rows}

    return data


@router.get("/api/agent-loop")
@cached(ttl=5)
def api_agent_loop():
    """Recent API call & tool stats from agent.log."""
    try:
        r = subprocess.run(
            ["tail", "-500", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return {"total_api": 0, "total_tool": 0, "avg_latency": 0,
                "total_tokens_in": 0, "total_tokens_out": 0, "tool_errors": 0,
                "api_calls": [], "tool_calls": []}

    lines = r.stdout.strip().split("\n")
    session = "20260619_235729_74dfff"
    api = []
    tools = []

    for line in lines:
        m = re.search(
            r"API call #(\d+): model=(\S+) provider=(\S+) in=(\d+) out=(\d+) "
            r"total=(\d+) latency=([\d.]+)s cache=(\d+)/(\d+)",
            line,
        )
        if m and session in line:
            api.append({
                "num": int(m.group(1)),
                "latency": float(m.group(7)),
                "in": int(m.group(4)),
                "out": int(m.group(5)),
                "cache": round(int(m.group(8)) / int(m.group(9)) * 100, 1),
            })
            continue
        m = re.search(r"tool (\w+) (completed|returned error) \(([\d.]+)s", line)
        if m and session in line:
            tools.append({
                "tool": m.group(1),
                "ok": m.group(2) == "completed",
                "dur": float(m.group(3)),
            })

    return {
        "api_calls": api[-20:],
        "tool_calls": tools[-20:],
        "total_api": len(api),
        "total_tool": len(tools),
        "avg_latency": round(sum(a["latency"] for a in api) / len(api), 1) if api else 0,
        "total_tokens_in": sum(a["in"] for a in api),
        "total_tokens_out": sum(a["out"] for a in api),
        "tool_errors": sum(1 for t in tools if not t["ok"]),
    }


@router.get("/api/stats")
@cached(ttl=5)
def api_stats():
    """Pipeline statistics, memory distribution, daily activity."""
    data: Dict[str, Any] = {"generated_at": datetime.now().isoformat()}

    # Model from config
    try:
        r = subprocess.run(
            ["grep", "-A2", "main:", str(_CONFIG_YAML)],
            capture_output=True, text=True,
        )
        for line in r.stdout.split("\n"):
            if "model:" in line:
                data["model"] = line.split("model:")[1].strip()
    except Exception:
        pass

    # Thread count
    try:
        r = subprocess.run(
            ["ps", "--no-headers", "-L", str(os.getpid())],
            capture_output=True, text=True,
        )
        data["threads"] = len(r.stdout.strip().split("\n"))
    except Exception:
        data["threads"] = 0

    # Pipeline totals
    rows = _query_db("SELECT COUNT(*) FROM pipeline_logs")
    data["pipeline_total"] = rows[0][0] if rows else 0

    rows = _query_db(
        "SELECT SUBSTR(created_at,1,10) as d, COUNT(*) FROM pipeline_logs "
        "WHERE created_at > datetime('now','-7 days') GROUP BY d ORDER BY d DESC"
    )
    data["pipeline_daily"] = {r[0]: r[1] for r in rows}

    rows = _query_db(
        "SELECT step, COUNT(*) as c FROM pipeline_logs "
        "WHERE created_at > datetime('now','-30 minutes') GROUP BY step ORDER BY c DESC"
    )
    data["pipeline_recent"] = {r[0]: r[1] for r in rows}

    rows = _query_db(
        "SELECT COUNT(*) FROM pipeline_logs "
        "WHERE created_at > datetime('now','-5 minutes')"
    )
    data["pipeline_5min"] = rows[0][0] if rows else 0

    rows = _query_db("SELECT layer, COUNT(*) FROM memory_operations GROUP BY layer")
    data["memory_layers"] = {r[0]: r[1] for r in rows}

    rows = _query_db("SELECT op, COUNT(*) FROM memory_operations GROUP BY op")
    data["memory_ops"] = {r[0]: r[1] for r in rows}

    rows = _query_db(
        "SELECT op, COUNT(*) FROM memory_operations WHERE created_at > '2026-06-19' GROUP BY op"
    )
    data["memory_today"] = {r[0]: r[1] for r in rows}

    return data


@router.get("/api/evolution")
@cached(ttl=15)
def api_evolution():
    """System 2 agent activity, extracts, memory writes evolution."""
    data: Dict[str, Any] = {}

    def safe_parse(s):
        if not s or not s.strip():
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {"_raw": str(s)[:100]}

    rows = _query_db(
        "SELECT created_at, step, parsed FROM pipeline_logs "
        "WHERE step LIKE 'SYSTEM2%' ORDER BY created_at DESC LIMIT 6"
    )
    data["s2"] = [{"ts": r[0][:19], "step": r[1], "detail": safe_parse(r[2])} for r in rows]

    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step='EXTRACT' ORDER BY created_at DESC LIMIT 8"
    )
    data["extracts"] = [{"ts": r[0][:19], "detail": safe_parse(r[1])} for r in rows]

    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step='DIGEST_SUMMARY' ORDER BY created_at DESC LIMIT 8"
    )
    data["writes"] = [{"ts": r[0][:19], "detail": safe_parse(r[1])} for r in rows]

    rows = _query_db("SELECT COUNT(*) FROM memory_operations WHERE op='SUPERSEDE'")
    data["supersede_count"] = rows[0][0] if rows else 0

    rows = _query_db("SELECT layer, count(*) FROM memory_operations WHERE op='ADD' GROUP BY layer")
    data["layer_dist"] = {r[0]: r[1] for r in rows}

    return data


@router.get("/api/timeline")
@cached(ttl=10)
def api_timeline():
    """Recent memory writes, S2 queue, system metrics, live pipeline."""
    data: Dict[str, Any] = {}

    # Hermes memory writes from kv table
    rows = _query_db(
        "SELECT key, substr(value,1,200) FROM kv "
        "WHERE key LIKE 'agentmem:write:%' ORDER BY rowid DESC LIMIT 20"
    )
    writes = []
    for r in rows:
        try:
            val = json.loads(r[1])
            writes.append({
                "memory_id": val.get("memory_id", "?"),
                "type": "write",
                "layer": val.get("layer", "?"),
                "text": (val.get("content", "") or "")[:120],
            })
        except Exception:
            pass

    rows = _query_db(
        "SELECT member FROM sorted_set "
        "WHERE set_key LIKE 'agentmem:s2:queue:%' ORDER BY rowid DESC LIMIT 5"
    )
    s2_entries = []
    for r in rows:
        try:
            val = json.loads(r[0])
            payload = val.get("payload", {})
            s2_entries.append({
                "memory_id": payload.get("memory_id", "?"),
                "created": (payload.get("created_at", "?") or "")[:10],
                "text": (payload.get("content", "") or "")[:120],
            })
        except Exception:
            pass

    rows = _query_db(
        "SELECT minute_ts, data FROM system_metrics ORDER BY minute_ts DESC LIMIT 10"
    )
    sys_metrics = []
    for r in rows:
        try:
            d = json.loads(r[1])
            d["ts"] = r[0]
            sys_metrics.append(d)
        except Exception:
            pass

    rows = _query_db(
        "SELECT step, COUNT(*) as c FROM pipeline_logs "
        "WHERE created_at > datetime('now','-5 minutes') GROUP BY step ORDER BY c DESC"
    )
    live = {r[0]: r[1] for r in rows}

    return {
        "writes": writes[:8],
        "s2_queue": s2_entries[:3],
        "system": sys_metrics,
        "live_5min": live,
    }


@router.get("/api/source")
async def api_source(path: str = Query(..., description="Absolute path to source file")):
    """Read a source file for the node-detail panel."""
    try:
        if not os.path.isfile(path):
            raise HTTPException(404, "File not found")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": path}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── serve the style page and SVG ──────────────────────────────────────────
# The plugin directory may be accessed through a symlink (common in WSL setups),
# so resolve() can land on an unexpected path. Try a few candidate locations.

def _find_resource(name: str) -> Path:
    candidates = [
        _EVOLUTION_DIR / name,
        _HERE / name,
        _HERE / "evolution_hub" / name,
        Path(__file__).parent.parent / "evolution_hub" / name,
    ]
    for p in candidates:
        if p.exists():
            return p
    return _EVOLUTION_DIR / name


_STYLE_HTML_PATH = _find_resource("evolution_hub_style.html")
_SVG_PATH = _find_resource("architecture.svg")
print(f"[evolution-hub] resources: style={_STYLE_HTML_PATH}, svg={_SVG_PATH}, exists={_SVG_PATH.exists()}")


@router.get("/evolution_hub_style")
async def serve_style_page():
    """Serve the evolution hub style page (reads the template HTML)."""
    p = _find_resource("evolution_hub_style.html")
    if not p.exists():
        raise HTTPException(404, "Page not found")
    from fastapi.responses import HTMLResponse
    html = p.read_text(encoding="utf-8")
    return HTMLResponse(html)


@router.get("/architecture.svg")
async def serve_svg():
    """Serve the architecture SVG."""
    p = _find_resource("architecture.svg")
    if not p.exists():
        raise HTTPException(404, "SVG not found")
    from fastapi.responses import Response
    svg = p.read_bytes()
    return Response(content=svg, media_type="image/svg+xml; charset=utf-8")
