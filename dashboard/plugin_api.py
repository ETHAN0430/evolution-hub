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

# Source base is configurable via env var; frontend can also pass absolute paths.
# Default matches the standard Hermes agent checkout location.
DEFAULT_SOURCE_BASE = Path(os.environ.get("HERMES_SOURCE_BASE", "/home/cyf/.hermes/hermes-agent"))


def _resolve_source_path(path: str) -> Path:
    """Resolve a source path that may be absolute or relative to the source base.

    Relative paths are resolved under HERMES_SOURCE_BASE. hy_memory/ paths are
    searched under any Python version inside venv/lib/python*/site-packages/.
    """
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p
    if p.is_absolute():
        # Absolute but not found; still return it so the caller gets a clean 404.
        return p

    candidates: list[Path] = []
    if path.startswith("hy_memory/"):
        suffix = path[len("hy_memory/"):]
        venv_site_packages = list(DEFAULT_SOURCE_BASE.glob("venv/lib/python*/site-packages/"))
        for sp in venv_site_packages:
            candidates.append(sp / suffix)
    else:
        candidates.append(DEFAULT_SOURCE_BASE / path)

    for c in candidates:
        if c.exists():
            return c

    # Fallback to the first candidate (or source-base joined path) for error reporting.
    return candidates[0] if candidates else DEFAULT_SOURCE_BASE / path

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


def _first_text(obj: Any, max_depth: int = 3) -> str:
    if max_depth <= 0:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        for item in obj:
            s = _first_text(item, max_depth - 1)
            if s:
                return s
    if isinstance(obj, dict):
        for v in obj.values():
            s = _first_text(v, max_depth - 1)
            if s:
                return s
    return ""


def _extract_summary(parsed: Any, keys: list[str]) -> str:
    if not isinstance(parsed, dict):
        return ""
    for k in keys:
        v = parsed.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            return v
        if isinstance(v, (list, dict)):
            s = _first_text(v)
            if s:
                return s
    return _first_text(parsed)


def _format_iso_time(ts: Any) -> str:
    if not ts:
        return ""
    s = str(ts)[:19]
    return s.replace(" ", "T") + "Z"


@router.get("/api/memory-feed")
@cached(ttl=5)
def api_memory_feed():
    """Recent L0~L7 memory operations from multiple sources."""
    layers = ["l1_raw", "l2_fact", "l3_summary", "l4_identity", "l5_knowledge", "l6_schema", "l7_intention"]
    recent = []

    # L1_raw: S1_L1_UPSERT in pipeline_logs
    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step='S1_L1_UPSERT' ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l1_raw",
            "op": "UPSERT",
            "summary": "写入 L1_RAW",
        })

    # L2_fact: memory_operations
    rows = _query_db(
        "SELECT created_at, op, content FROM memory_operations "
        "WHERE layer='l2_fact' ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        content = r[2] or ""
        summary = content[:60] + "..." if len(content) > 60 else content
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l2_fact",
            "op": r[1] or "",
            "summary": summary,
        })

    # L3_summary: SUMMARY / DIGEST_SUMMARY in pipeline_logs
    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step IN ('SUMMARY','DIGEST_SUMMARY') ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        parsed = {}
        try:
            if r[1]:
                parsed = json.loads(r[1])
        except Exception:
            parsed = {}
        summary = _extract_summary(parsed, ["summary"])
        if len(summary) > 60:
            summary = summary[:60] + "..."
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l3_summary",
            "op": "SUMMARY",
            "summary": summary or "生成摘要",
        })

    # L4_identity: memory_operations
    rows = _query_db(
        "SELECT created_at, op, content FROM memory_operations "
        "WHERE layer='l4_identity' ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        content = r[2] or ""
        summary = content[:60] + "..." if len(content) > 60 else content
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l4_identity",
            "op": r[1] or "",
            "summary": summary,
        })

    # L5_knowledge: RECONCILE in pipeline_logs
    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step='RECONCILE' ORDER BY created_at DESC LIMIT 5"
    )
    for r in rows:
        parsed = {}
        try:
            if r[1]:
                parsed = json.loads(r[1])
        except Exception:
            parsed = {}
        summary = _extract_summary(parsed, ["knowledge", "content", "summary", "result"])
        if len(summary) > 60:
            summary = summary[:60] + "..."
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l5_knowledge",
            "op": "RECONCILE",
            "summary": summary or "知识层调和",
        })

    # L6_schema & L7_intention: SYSTEM2_AGENT in pipeline_logs
    rows = _query_db(
        "SELECT created_at, parsed FROM pipeline_logs "
        "WHERE step='SYSTEM2_AGENT' ORDER BY created_at DESC LIMIT 20"
    )
    for r in rows:
        parsed = {}
        try:
            if r[1]:
                parsed = json.loads(r[1])
        except Exception:
            parsed = {}
        tokens = parsed.get("total_tokens", 0)
        success = "完成" if parsed.get("success") else "失败"
        elapsed = parsed.get("elapsed_ms", 0)
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l6_schema",
            "op": "SYSTEM2",
            "summary": f"System 2 {success} · {tokens} tokens · {elapsed:.0f}ms",
        })
        recent.append({
            "time": _format_iso_time(r[0]),
            "layer": "l7_intention",
            "op": "SYSTEM2",
            "summary": f"System 2 {success} · {tokens} tokens · {elapsed:.0f}ms",
        })

    recent.sort(key=lambda x: x["time"], reverse=True)
    return {"recent": recent, "layers": layers, "error": None}


@router.get("/api/prefetch-feed")
@cached(ttl=5)
def api_prefetch_feed():
    """Recent prefetch queries and hit counts from pipeline_logs."""
    rows = _query_db(
        "SELECT created_at, step, prompt, parsed FROM pipeline_logs "
        "WHERE step IN ('READ_REQUEST','READ_SUMMARY') ORDER BY created_at DESC LIMIT 10"
    )
    recent = []
    for r in rows:
        parsed = {}
        try:
            if r[3]:
                parsed = json.loads(r[3])
        except Exception:
            parsed = {}
        query = r[2] or ""
        if len(query) > 120:
            query = query[:120] + "..."
        hits = parsed.get("total_found", 0) if isinstance(parsed, dict) else 0
        reader = parsed.get("reader", "legacy") if isinstance(parsed, dict) else "legacy"
        recent.append({
            "time": _format_iso_time(r[0]),
            "query": query,
            "hits": hits,
            "reader": reader,
        })

    total_1h = _query_db(
        "SELECT COUNT(*) FROM pipeline_logs WHERE step IN ('READ_REQUEST','READ_SUMMARY') "
        "AND created_at > datetime('now','-1 hour')"
    )
    total_today = _query_db(
        "SELECT COUNT(*) FROM pipeline_logs WHERE step IN ('READ_REQUEST','READ_SUMMARY') "
        "AND created_at > date('now')"
    )
    return {
        "recent": recent,
        "stats": {
            "total_1h": total_1h[0][0] if total_1h else 0,
            "total_today": total_today[0][0] if total_today else 0,
        },
        "error": None,
    }


def _active_profile() -> str:
    """Read active_profile from Hermes config, fallback to 'default'."""
    try:
        if _CONFIG_YAML.exists():
            r = subprocess.run(
                ["grep", "-E", "^active_profile:", str(_CONFIG_YAML)],
                capture_output=True, text=True, timeout=3,
            )
            for line in r.stdout.split("\n"):
                if "active_profile:" in line:
                    return line.split("active_profile:", 1)[1].strip() or "default"
    except Exception:
        pass
    return "default"


@router.get("/api/self-improvement")
@cached(ttl=5)
def api_self_improvement():
    """Sniff local self-improvement signals: memory files, skills, agent.log."""
    profile = _active_profile()
    base = Path.home() / ".hermes" / "memories"

    memory_updates = {}
    for name in ["MEMORY.md", "USER.md"]:
        try:
            p = base / name
            if p.exists():
                memory_updates[name] = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
        except Exception:
            pass

    recent_skills = []
    skill_dirs = [
        Path.home() / ".hermes" / "skills",
        base / "skills",
    ]
    cutoff = datetime.now().timestamp() - 5 * 24 * 3600
    seen = set()
    for d in skill_dirs:
        try:
            if not d.exists():
                continue
            for p in d.iterdir():
                if p.name.startswith("."):
                    continue
                key = str(p.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    st = p.stat()
                    if st.st_mtime < cutoff and st.st_ctime < cutoff:
                        continue
                    first_line = ""
                    with open(p, "r", encoding="utf-8") as f:
                        first_line = f.readline().strip()
                    recent_skills.append({
                        "name": p.stem,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                        "preview": (first_line[:80] + "...") if len(first_line) > 80 else first_line,
                    })
                except Exception:
                    pass
        except Exception:
            pass
    recent_skills.sort(key=lambda x: x["modified"], reverse=True)
    recent_skills = recent_skills[:10]

    recent_tool_calls = []
    try:
        r = subprocess.run(
            ["grep", "-iE", "memory.updated|memory.updating|skill.created|skill.updated|memory_add completed|memory returned error", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        lines = [ln for ln in r.stdout.strip().split("\n") if ln.strip()]
        for line in lines[-5:]:
            ts = ""
            m = re.match(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", line)
            if m:
                ts = m.group(1).replace(" ", "T")
            low = line.lower()
            tool = "memory" if "memory" in low else "skill"
            if "created" in low:
                action = "create"
            else:
                action = "update"
            summary = line if len(line) <= 100 else line[:100] + "..."
            recent_tool_calls.append({
                "time": ts,
                "tool": tool,
                "action": action,
                "summary": summary,
            })
    except Exception:
        pass

    return {
        "memory_updates": memory_updates,
        "recent_skills": recent_skills,
        "recent_tool_calls": recent_tool_calls,
        "error": None,
    }


@router.get("/api/architecture")
async def api_architecture():
    """Serve the architecture graph data (nodes + connections) from the plugin dist directory."""
    p = Path(__file__).resolve().parent / "dist" / "architecture.json"
    if not p.exists():
        raise HTTPException(404, "architecture.json not found")
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/api/source")
async def api_source(
    path: str = Query(..., description="Absolute or relative path to source file"),
    loc: str = Query(None, description="Line number or function/class name to focus on"),
):
    """Read a source file for the node-detail panel. Optionally return a snippet around loc."""
    try:
        resolved = _resolve_source_path(path)
        if not resolved.is_file():
            raise HTTPException(404, f"File not found: {resolved}")
        with open(resolved, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not loc:
            return {"content": "".join(lines), "path": str(resolved)}
        # Try to interpret loc as a 1-based line number
        try:
            line_no = int(loc)
        except ValueError:
            line_no = None
            best_indent = None
            pattern = re.compile(r"^(\s*)(def|class)\s+" + re.escape(loc) + r"\b")
            for i, line in enumerate(lines, start=1):
                m = pattern.match(line)
                if m:
                    indent = len(m.group(1))
                    if best_indent is None or indent < best_indent:
                        line_no = i
                        best_indent = indent
                        if indent == 0:
                            break
            if line_no is None:
                return {
                    "content": "".join(lines),
                    "path": str(resolved),
                    "loc": loc,
                    "error": "definition not found",
                }
        is_numeric_loc = loc.isdigit() if isinstance(loc, str) else True
        if is_numeric_loc:
            start = max(0, line_no - 6)
            end = min(len(lines), line_no + 9)
        else:
            # For function/class names, return the whole definition (signature + body)
            # up to the next sibling/peer definition, capped at ~200 lines.
            def_idx = line_no - 1
            def_indent = len(re.match(r"^(\s*)", lines[def_idx]).group(1))
            start = def_idx
            while start > 0:
                prev = lines[start - 1]
                m = re.match(r"^(\s*)@", prev)
                if m and len(m.group(1)) == def_indent:
                    start -= 1
                else:
                    break
            end = len(lines)
            boundary = re.compile(r"^(\s*)(def|class)\b")
            for j in range(line_no, len(lines)):
                m = boundary.match(lines[j])
                if m and len(m.group(1)) <= def_indent:
                    end = j
                    break
            if end - start > 200:
                end = start + 200
        snippet = "".join(lines[start:end])
        return {"content": snippet, "path": str(resolved), "line": line_no, "start": start + 1, "end": end}
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
