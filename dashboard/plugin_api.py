"""
hermes-evolution-hub Dashboard plugin backend API.
Mounted at /api/plugins/hermes-evolution-hub/ by Hermes Dashboard (9119).

Target: Cognitive OS (decision-grade memory ledger), not HY Memory.
"""
import functools
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

try:
    from hermes_constants import get_hermes_home
except ImportError:
    def get_hermes_home() -> Path:
        value = (os.environ.get("HERMES_HOME") or "").strip()
        return Path(value) if value else Path.home() / ".hermes"


router = APIRouter(tags=["evolution-hub"])

# ── paths ──────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent.parent
_EVOLUTION_DIR = _HERE / "evolution_hub"
_HERMES_HOME = get_hermes_home()
_AGENT_LOG = _HERMES_HOME / "logs" / "agent.log"
_CONFIG_YAML = _HERMES_HOME / "config.yaml"

# Cognitive OS DB — follows the same resolution logic as hermes_provider.py
_COGNITIVE_OS_DB = Path(
    os.environ.get(
        "COGNITIVE_OS_DB",
        str(Path.home() / "projects" / "cognitive-os" / "data" / "cognitive.db"),
    )
)

# Source base is configurable via env var.
DEFAULT_SOURCE_BASE = Path(os.environ.get("HERMES_SOURCE_BASE", str(Path(__file__).resolve().parents[3])))


def _resolve_source_path(path: str) -> Path:
    """Resolve a source path that may be absolute or relative to the source base."""
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p
    if p.is_absolute():
        return p

    candidates: list[Path] = []
    if path.startswith("cognitive_os/"):
        suffix = path[len("cognitive_os/"):]
        # Look in the cognitive-os project
        project = Path.home() / "projects" / "cognitive-os"
        candidates.append(project / path)
    else:
        candidates.append(DEFAULT_SOURCE_BASE / path)

    for c in candidates:
        if c.exists():
            return c
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
    """Direct SQLite queries on the Cognitive OS ledger DB."""
    try:
        conn = sqlite3.connect(str(_COGNITIVE_OS_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        return []


def _query_cognitive_maintenance(sql: str, params: tuple = ()):
    """Maintenance reads must surface failures; an error is not an empty inbox."""
    conn = sqlite3.connect(f"file:{_COGNITIVE_OS_DB.as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _row_count(table: str) -> int:
    rows = _query_db(f"SELECT COUNT(*) AS cnt FROM {table}")
    return rows[0]["cnt"] if rows else 0


def _table_exists(table: str) -> bool:
    rows = _query_db(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return bool(rows)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_utc(value: str) -> datetime | None:
    """Best-effort ISO timestamp parser for display-only review state."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@router.get("/api/maintenance-inbox")
def api_maintenance_inbox():
    """Read-only Cognitive OS inbox adapter with explicit provenance and errors."""
    as_of = _now_iso()
    try:
        issues = _query_cognitive_maintenance(
            "SELECT id, kind, severity, target_type, target_id, detail_json, detected_at "
            "FROM maintenance_issues WHERE resolved_at IS NULL ORDER BY detected_at, id"
        )
        proposals = _query_cognitive_maintenance(
            "SELECT id, kind, target_type, target_id, suggested_action, rationale, status, created_at "
            "FROM proposals WHERE status='pending' ORDER BY created_at, id"
        )
        state = _query_cognitive_maintenance(
            "SELECT ledger_watermark, projected_at, status, error, projection_version "
            "FROM projection_state WHERE projection_name='kuzu'"
        )
        has_change_log = _query_cognitive_maintenance(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_changes'"
        )
        if has_change_log:
            count_rows = _query_cognitive_maintenance("SELECT COALESCE(MAX(seq), 0) AS watermark FROM ledger_changes")
        else:
            count_rows = _query_cognitive_maintenance(
                "SELECT " + " + ".join(f"(SELECT COUNT(*) FROM {name})" for name in
                    ("evidence", "claims", "models", "decisions", "intents", "outcomes", "object_relations")) + " AS watermark"
            )
        projection = dict(state[0]) if state else None
        lag = None if projection is None else max(0, int(count_rows[0]["watermark"]) - int(projection["ledger_watermark"]))
        return {
            "source": "SQLite Ledger", "as_of": as_of, "error": None, "projection_lag": lag,
            "projection": projection,
            "columns": {
                "decisions_to_review": [dict(r) for r in issues if r["kind"] == "decision_overdue"],
                "reality_contradictions": [dict(r) for r in issues if r["kind"] == "outcome_contradicts_active_claim"],
                "pending_proposals": [dict(r) for r in proposals],
                "data_hygiene": [dict(r) for r in issues if r["kind"] not in {"decision_overdue", "outcome_contradicts_active_claim"}],
            },
        }
    except Exception as error:
        return {"source": "SQLite Ledger", "as_of": as_of, "projection_lag": None,
                "error": f"{type(error).__name__}: {error}", "columns": None}


@router.get("/api/review")
@cached(ttl=5)
def api_review():
    """Read-only audit view for reviewing Cognitive OS' decision ledger.

    The endpoint deliberately never proposes, accepts, or mutates anything. It
    surfaces the evidence boundary and the outstanding review work so that a
    human can judge the ledger rather than treating it as automatic truth.
    """
    if not _COGNITIVE_OS_DB.exists():
        return {"source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(),
                "error": f"ledger not found: {_COGNITIVE_OS_DB}", "summary": {}, "queues": {}}
    try:
        now = datetime.now(timezone.utc)
        claims = []
        if _table_exists("claims") and _table_exists("claim_evidence") and _table_exists("evidence"):
            rows = _query_cognitive_maintenance(
                "SELECT c.id, c.statement, c.kind, c.status, c.falsifier, "
                "COUNT(DISTINCT ce.evidence_id) AS evidence_count, "
                "COUNT(DISTINCT e.source_ref) AS source_count, "
                "GROUP_CONCAT(DISTINCT e.source_ref) AS source_refs "
                "FROM claims c "
                "LEFT JOIN claim_evidence ce ON ce.claim_id=c.id "
                "LEFT JOIN evidence e ON e.id=ce.evidence_id "
                "GROUP BY c.id ORDER BY c.rowid DESC LIMIT 24"
            )
            claims = [dict(row) for row in rows]

        decisions = []
        if _table_exists("decisions"):
            rows = _query_cognitive_maintenance(
                "SELECT d.id, d.question, d.selected_option, d.core_bet, d.falsifiers_json, d.review_at, d.status, "
                "COUNT(DISTINCT dc.claim_id) AS claim_count, "
                "COUNT(DISTINCT o.id) AS outcome_count, "
                "SUM(CASE WHEN o.implication='contradicts' THEN 1 ELSE 0 END) AS contradiction_count "
                "FROM decisions d "
                "LEFT JOIN decision_claims dc ON dc.decision_id=d.id "
                "LEFT JOIN outcomes o ON o.decision_id=d.id "
                "GROUP BY d.id ORDER BY d.rowid DESC LIMIT 18"
            )
            for row in rows:
                item = dict(row)
                review_at = _as_utc(item.get("review_at", ""))
                item["review_state"] = "overdue" if review_at and review_at < now and item.get("status") == "active" else "scheduled"
                item["contradiction_count"] = int(item.get("contradiction_count") or 0)
                decisions.append(item)

        models = []
        if _table_exists("models") and _table_exists("object_relations") and _table_exists("claim_evidence") and _table_exists("evidence"):
            rows = _query_cognitive_maintenance(
                "SELECT m.id, m.proposition, m.status, "
                "COUNT(DISTINCT r.source_id) AS support_claim_count, "
                "COUNT(DISTINCT e.source_ref) AS support_source_count "
                "FROM models m "
                "LEFT JOIN object_relations r ON r.target_type='model' AND r.target_id=m.id "
                "AND r.source_type='claim' AND r.key='supports_model' "
                "LEFT JOIN claim_evidence ce ON ce.claim_id=r.source_id "
                "LEFT JOIN evidence e ON e.id=ce.evidence_id "
                "GROUP BY m.id ORDER BY m.rowid DESC LIMIT 12"
            )
            for row in rows:
                item = dict(row)
                item["admission_state"] = "ready" if item["support_claim_count"] >= 2 and item["support_source_count"] >= 2 else "insufficient_support"
                models.append(item)

        intents = []
        if _table_exists("intents"):
            rows = _query_cognitive_maintenance(
                "SELECT id, action, trigger_kind, trigger_value, valid_until, status "
                "FROM intents ORDER BY rowid DESC LIMIT 18"
            )
            for row in rows:
                item = dict(row)
                valid_until = _as_utc(item.get("valid_until", ""))
                item["expiry_state"] = "expired" if valid_until and valid_until < now and item.get("status") == "active" else "valid"
                intents.append(item)

        outcomes = []
        if _table_exists("outcomes"):
            rows = _query_cognitive_maintenance(
                "SELECT id, decision_id, observation, implication, observed_at "
                "FROM outcomes ORDER BY observed_at DESC LIMIT 18"
            )
            outcomes = [dict(row) for row in rows]

        proposals = []
        issues = []
        if _table_exists("proposals"):
            proposals = [dict(row) for row in _query_cognitive_maintenance(
                "SELECT id, kind, target_type, target_id, suggested_action, rationale, created_at "
                "FROM proposals WHERE status='pending' ORDER BY created_at DESC LIMIT 12"
            )]
        if _table_exists("maintenance_issues"):
            issues = [dict(row) for row in _query_cognitive_maintenance(
                "SELECT id, kind, severity, target_type, target_id, detail_json, detected_at "
                "FROM maintenance_issues WHERE resolved_at IS NULL ORDER BY detected_at DESC LIMIT 12"
            )]

        unbacked_claims = [item for item in claims if not item["evidence_count"]]
        unfalsifiable_claims = [item for item in claims if not str(item.get("falsifier") or "").strip()]
        overdue_decisions = [item for item in decisions if item["review_state"] == "overdue"]
        expired_intents = [item for item in intents if item["expiry_state"] == "expired"]
        contradictions = [item for item in outcomes if item.get("implication") == "contradicts"]
        weak_models = [item for item in models if item["admission_state"] == "insufficient_support"]

        return {
            "source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(), "error": None,
            "summary": {
                "evidence": _row_count("evidence") if _table_exists("evidence") else 0,
                "claims": _row_count("claims") if _table_exists("claims") else 0,
                "decisions": _row_count("decisions") if _table_exists("decisions") else 0,
                "outcomes": _row_count("outcomes") if _table_exists("outcomes") else 0,
                "unbacked_claims": len(unbacked_claims),
                "unfalsifiable_claims": len(unfalsifiable_claims),
                "overdue_decisions": len(overdue_decisions),
                "expired_intents": len(expired_intents),
                "contradictions": len(contradictions),
                "weak_models": len(weak_models),
                "pending_issues": len(issues),
                "pending_proposals": len(proposals),
            },
            "queues": {
                "claims": claims, "decisions": decisions, "models": models, "intents": intents,
                "outcomes": outcomes, "issues": issues, "proposals": proposals,
            },
        }
    except Exception as error:
        return {"source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(),
                "error": f"{type(error).__name__}: {error}", "summary": {}, "queues": {}}


# ── API endpoints ─────────────────────────────────────────────────────────


@router.get("/api/health")
@cached(ttl=5)
def api_health():
    """Health: ledger stats + agent activity."""
    data: Dict[str, Any] = {}

    # 1. Ledger record counts → replace HY Memory server status
    db_ok = _COGNITIVE_OS_DB.exists()
    if db_ok:
        data["server"] = {
            "vdb": "ok" if _table_exists("claims") else "empty",
            "embed": "ok",
            "llm": "ok",
            "vdb_points": sum(
                _row_count(t)
                for t in ["evidence", "claims", "models", "decisions", "intents", "outcomes"]
                if _table_exists(t)
            ),
        }
    else:
        data["server"] = {"vdb": "down", "embed": "down", "llm": "down", "vdb_points": 0}

    # 2. Recent writes (last hour) — counts per ledger table
    meta_1h: dict[str, int] = {}
    for table, label in [
        ("evidence", "Evidence"),
        ("claims", "Claim"),
        ("models", "Model"),
        ("decisions", "Decision"),
        ("intents", "Intent"),
        ("outcomes", "Outcome"),
        ("object_relations", "Relation"),
    ]:
        if _table_exists(table) and _table_has_time(table):
            rows = _query_db(
                f"SELECT COUNT(*) AS cnt FROM {table} WHERE rowid > "
                f"(SELECT IFNULL(MAX(rowid), 0) - 100 FROM {table})"
            )
            meta_1h[label] = rows[0]["cnt"] if rows else 0
    data["pipeline_1h"] = meta_1h

    # 3. Prefetch stats from agent.log
    try:
        r = subprocess.run(
            ["grep", "-E", "prefetch|memory_search|memory_add", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        recent = r.stdout.strip().split("\n")[-30:]
        data["prefetch"] = {
            "ok": sum(1 for l in recent if "hits=" in l or "memory_search" in l),
            "fail": sum(1 for l in recent if "failed" in l or "error" in l.lower()),
        }
    except Exception:
        data["prefetch"] = {"ok": 0, "fail": 0}

    return data


def _table_has_time(table: str) -> bool:
    """Check if table has an observed_at, created_at, or valid_until column."""
    rows = _query_db(f"PRAGMA table_info({table})")
    cols = {r["name"] for r in rows}
    return bool(cols & {"observed_at", "created_at", "valid_until"})


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
    api = []
    tools = []
    token_in = 0
    token_out = 0
    total_latency = 0
    api_count = 0
    tool_errors = 0

    for line in lines[-200:]:
        if "API call" in line:
            api.append(line[-120:])
            api_count += 1
            m = re.search(r"latency=([\d.]+)", line)
            if m:
                total_latency += float(m.group(1))
            m = re.search(r"tokens=(\d+)\+(\d+)", line)
            if m:
                token_in += int(m.group(1))
                token_out += int(m.group(2))
        if "Tool call" in line or "tool_call" in line:
            tools.append(line[-120:])
        if "tool error" in line.lower() or "ToolError" in line:
            tool_errors += 1

    return {
        "total_api": api_count,
        "total_tool": len(tools),
        "avg_latency": round(total_latency / api_count, 2) if api_count else 0,
        "total_tokens_in": token_in,
        "total_tokens_out": token_out,
        "tool_errors": tool_errors,
        "api_calls": api[-10:],
        "tool_calls": tools[-10:],
    }


@router.get("/api/stats")
@cached(ttl=10)
def api_stats():
    """Ledger aggregate stats."""
    data: Dict[str, Any] = {}

    # Table counts
    tables = ["evidence", "claims", "models", "decisions", "intents", "outcomes"]
    for t in tables:
        data[t] = _row_count(t) if _table_exists(t) else 0

    # Relation types
    data["relation_types"] = {}
    if _table_exists("relation_types"):
        rows = _query_db("SELECT key, source_type, target_type, description FROM relation_types")
        data["relation_types"] = {r["key"]: {"source": r["source_type"], "target": r["target_type"]} for r in rows}

    # Relation counts by type
    data["relations_by_type"] = {}
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, COUNT(*) AS cnt FROM object_relations GROUP BY key")
        data["relations_by_type"] = {r["key"]: r["cnt"] for r in rows}
        data["total_relations"] = sum(data["relations_by_type"].values())

    # Claim status distribution
    if _table_exists("claims"):
        rows = _query_db("SELECT status, COUNT(*) AS cnt FROM claims GROUP BY status")
        data["claim_status"] = {r["status"]: r["cnt"] for r in rows}

    # Decision status distribution
    if _table_exists("decisions"):
        rows = _query_db("SELECT status, COUNT(*) AS cnt FROM decisions GROUP BY status")
        data["decision_status"] = {r["status"]: r["cnt"] for r in rows}

    return data


@router.get("/api/evolution")
@cached(ttl=15)
def api_evolution():
    """Recent ledger writes as 'evolution' steps."""
    data: Dict[str, Any] = {}
    steps = []

    for table, label in [
        ("evidence", "Evidence"),
        ("claims", "Claim"),
        ("models", "Model"),
        ("decisions", "Decision"),
        ("intents", "Intent"),
        ("outcomes", "Outcome"),
    ]:
        if not _table_exists(table):
            continue
        time_col = "observed_at" if table in ("evidence", "outcomes") else None
        if time_col:
            rows = _query_db(
                f"SELECT id, {time_col} AS ts FROM {table} ORDER BY rowid DESC LIMIT 5"
            )
        else:
            rows = _query_db(
                f"SELECT id FROM {table} ORDER BY rowid DESC LIMIT 5"
            )
        for r in rows:
            steps.append({
                "layer": f"ledger/{label}",
                "id": r["id"],
                "time": r["ts"] if "ts" in r else _now_iso(),
                "type": label,
            })

    data["steps"] = steps[:20]
    return data


@router.get("/api/timeline")
@cached(ttl=5)
def api_timeline():
    """Recent ledger writes in chronological-ish order."""
    items = []
    for table, label, content_col in [
        ("evidence", "Evidence", "content"),
        ("claims", "Claim", "statement"),
        ("models", "Model", "proposition"),
        ("decisions", "Decision", "question"),
        ("intents", "Intent", "action"),
        ("outcomes", "Outcome", "observation"),
    ]:
        if not _table_exists(table):
            continue
        if table in ("evidence", "outcomes"):
            sql = f"SELECT id, {content_col} AS txt, observed_at AS ts FROM {table} ORDER BY rowid DESC LIMIT 5"
        elif table == "intents":
            sql = f"SELECT id, {content_col} AS txt, valid_until AS ts FROM {table} ORDER BY rowid DESC LIMIT 5"
        else:
            sql = f"SELECT id, {content_col} AS txt FROM {table} ORDER BY rowid DESC LIMIT 5"
        rows = _query_db(sql)
        for r in rows:
            items.append({
                "id": r["id"],
                "content": (r["txt"] or "")[:100],
                "type": label,
                "time": r["ts"] if "ts" in r else _now_iso(),
            })

    items.sort(key=lambda x: x.get("time", ""), reverse=True)
    return {"items": items[:20]}


@router.get("/api/memory-feed")
@cached(ttl=5)
def api_memory_feed():
    """Ledger records grouped by type → mapped to the L0~L7 mental model."""
    layers = ["Evidence", "Claim", "Model", "Decision", "Intent", "Outcome"]
    recent = []

    for layer, table, content_col in [
        ("Evidence", "evidence", "content"),
        ("Claim", "claims", "statement"),
        ("Model", "models", "proposition"),
        ("Decision", "decisions", "question"),
        ("Intent", "intents", "action"),
        ("Outcome", "outcomes", "observation"),
    ]:
        if not _table_exists(table):
            continue
        time_col = "observed_at" if table in ("evidence", "outcomes") else None
        if time_col:
            sql = f"SELECT id, {content_col} AS txt FROM {table} ORDER BY rowid DESC LIMIT 5"
        else:
            sql = f"SELECT id, {content_col} AS txt FROM {table} ORDER BY rowid DESC LIMIT 5"
        rows = _query_db(sql)
        for r in rows:
            recent.append({
                "layer": layer,
                "time": _now_iso(),
                "op": "ADD",
                "summary": (r["txt"] or "")[:120],
                "id": r["id"],
            })

    return {"layers": layers, "recent": recent, "total": len(recent)}


@router.get("/api/prefetch-feed")
@cached(ttl=5)
def api_prefetch_feed():
    """Memory search / recall stats from agent.log."""
    try:
        r = subprocess.run(
            ["grep", "-E", "memory_search|prefetch|autoRecall", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return {"recent": [], "stats": {"total_1h": 0, "total_today": 0}}

    lines = r.stdout.strip().split("\n")
    recent = []
    for line in lines[-15:]:
        hits = 0
        m = re.search(r"hits[=:](\d+)", line)
        if m:
            hits = int(m.group(1))
        else:
            hits = 1 if "memory_search" in line or "autoRecall" in line else 0
        recent.append({
            "time": _now_iso(),
            "hits": hits,
            "query": line[-100:],
            "reader": "cognitive-os",
        })

    return {
        "recent": recent,
        "stats": {
            "total_1h": len(lines),
            "total_today": len(lines),
        },
    }


@router.get("/api/self-improvement")
@cached(ttl=5)
def api_self_improvement():
    """Sniff memory files, skills, and recent tool calls."""
    data: Dict[str, Any] = {}

    # Memory files
    memory_updates: Dict[str, str] = {}
    for name in ["MEMORY.md", "USER.md"]:
        p = _HERMES_HOME / name
        if p.exists():
            memory_updates[name] = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
    data["memory_updates"] = memory_updates

    # Recent skills
    skills_dir = _HERMES_HOME / "skills"
    recent_skills = []
    if skills_dir.exists():
        try:
            r = subprocess.run(
                ["find", str(skills_dir), "-name", "SKILL.md", "-newer", str(_COGNITIVE_OS_DB)],
                capture_output=True, text=True, timeout=3,
            )
            for path in r.stdout.strip().split("\n"):
                if not path.strip():
                    continue
                p = Path(path.strip())
                recent_skills.append({
                    "name": p.parent.name,
                    "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
        except Exception:
            pass
    data["recent_skills"] = recent_skills[:10]

    # Recent memory-related tool calls from agent.log
    try:
        r = subprocess.run(
            ["grep", "-E", "memory_add|memory_search|skill_manage", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        tool_lines = r.stdout.strip().split("\n")[-10:]
        data["recent_tool_calls"] = [
            {
                "tool": "memory",
                "action": "add/search/manage",
                "summary": line[-80:],
                "time": _now_iso(),
            }
            for line in tool_lines
            if line.strip()
        ]
    except Exception:
        data["recent_tool_calls"] = []

    return data


@router.get("/api/cognitive-quality")
@cached(ttl=5)
def api_cognitive_quality():
    """Ledger health & quality metrics."""
    latest: Dict[str, Any] = {}
    health: Dict[str, Any] = {}
    reports: list[dict] = []
    recent_ops: list[dict] = []

    # Edge type counts
    edge_counts: Dict[str, int] = {}
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, COUNT(*) AS cnt FROM object_relations GROUP BY key")
        edge_counts = {r["key"]: r["cnt"] for r in rows}
    latest["edge_type_counts"] = edge_counts
    health["edge_type_counts"] = edge_counts

    # Record counts
    evidence_count = _row_count("evidence") if _table_exists("evidence") else 0
    claim_count = _row_count("claims") if _table_exists("claims") else 0
    model_count = _row_count("models") if _table_exists("models") else 0
    decision_count = _row_count("decisions") if _table_exists("decisions") else 0
    intent_count = _row_count("intents") if _table_exists("intents") else 0
    outcome_count = _row_count("outcomes") if _table_exists("outcomes") else 0
    total_records = evidence_count + claim_count + model_count + decision_count + intent_count + outcome_count

    total_edges = sum(edge_counts.values())

    health["schema_total"] = claim_count + model_count + decision_count
    health["memory_edge_total"] = total_edges
    health["cognitive_edge_total"] = total_edges
    health["related_to_ratio"] = 0.0  # no generic RELATED_TO edges in Cognitive OS

    # Orphans: claims without evidence
    orphan_schema = 0
    no_evidence_schema = 0
    if _table_exists("claims") and _table_exists("claim_evidence"):
        rows = _query_db(
            "SELECT COUNT(*) AS cnt FROM claims c "
            "WHERE NOT EXISTS (SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id)"
        )
        orphan_schema = rows[0]["cnt"] if rows else 0
        no_evidence_schema = orphan_schema
    health["orphan_schema_count"] = orphan_schema
    health["no_evidence_schema_count"] = no_evidence_schema

    latest["schema_created"] = claim_count + model_count + decision_count
    latest["schema_reused"] = 0
    latest["evidence_added"] = evidence_count
    latest["edges_created"] = total_edges
    latest["related_to_ratio"] = 0.0
    latest["warnings"] = []
    if orphan_schema:
        latest["warnings"].append(f"{orphan_schema} claims without evidence")

    # Graph ops = recent relations
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, source_type FROM object_relations ORDER BY rowid DESC LIMIT 5")
        for r in rows:
            recent_ops.append({
                "time": _now_iso(),
                "op": "RELATION",
                "edge_type": r["key"],
            })

    health["graph_ops"] = {"total": total_edges}

    return {
        "latest": latest,
        "reports": reports,
        "health": health,
        "recent_ops": recent_ops,
    }


@router.get("/api/decision-workspace")
@cached(ttl=5)
def api_decision_workspace():
    """Decision workspace — Evidence/Claim/Model/Decision/Intent/Outcome grouped."""
    data: Dict[str, Any] = {}

    # Source overview
    data["source"] = {
        "vdb_total": _row_count("evidence") if _table_exists("evidence") else 0,
        "graph_total": _row_count("claims") if _table_exists("claims") else 0,
    }

    # Graph health
    health: Dict[str, Any] = {}
    health["schema_total"] = (_row_count("claims") if _table_exists("claims") else 0) \
        + (_row_count("models") if _table_exists("models") else 0) \
        + (_row_count("decisions") if _table_exists("decisions") else 0)
    health["memory_edge_total"] = _row_count("object_relations") if _table_exists("object_relations") else 0
    health["cognitive_edge_total"] = health["memory_edge_total"]

    # Orphan count
    orphan = 0
    if _table_exists("claims") and _table_exists("claim_evidence"):
        rows = _query_db(
            "SELECT COUNT(*) AS cnt FROM claims c "
            "WHERE NOT EXISTS (SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id)"
        )
        orphan = rows[0]["cnt"] if rows else 0
    health["orphan_schema_count"] = orphan
    data["graph_health"] = health

    # Claims
    claims_items = []
    if _table_exists("claims"):
        rows = _query_db("SELECT id, statement, status, kind FROM claims ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            claims_items.append({
                "id": r["id"],
                "time": _now_iso(),
                "content": (r["statement"] or "")[:120],
                "status": r["status"],
                "tags": [r["kind"]],
            })
    data["claims"] = {"source": "Cognitive OS Ledger", "items": claims_items}

    # Models
    models_items = []
    if _table_exists("models"):
        rows = _query_db("SELECT id, proposition, status FROM models ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            models_items.append({
                "id": r["id"],
                "time": _now_iso(),
                "content": (r["proposition"] or "")[:120],
                "status": r["status"],
            })
    data["models"] = {"source": "Cognitive OS Ledger", "items": models_items}

    # Decisions + Intents as "contracts"
    contracts_items = []
    if _table_exists("decisions"):
        rows = _query_db("SELECT id, question, selected_option, status FROM decisions ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            contracts_items.append({
                "id": r["id"],
                "time": _now_iso(),
                "content": f"Q: {(r['question'] or '')[:80]} → {r['selected_option']}",
                "status": r["status"],
            })
    data["contracts"] = {"source": "Decision Ledger", "items": contracts_items}

    # Intents
    intent_items = []
    if _table_exists("intents"):
        rows = _query_db(
            "SELECT id, action, status, valid_until FROM intents ORDER BY rowid DESC LIMIT 6"
        )
        for r in rows:
            intent_items.append({
                "id": r["id"],
                "time": r["valid_until"] or _now_iso(),
                "content": (r["action"] or "")[:120],
                "status": r["status"],
                "tags": [f"until {r['valid_until'][:10]}" if r["valid_until"] else ""],
            })
    data["intents"] = {"source": "Intent Ledger", "items": intent_items}

    # Decision ledger message
    if _table_exists("decisions"):
        decision_count = _row_count("decisions")
        outcome_count = _row_count("outcomes") if _table_exists("outcomes") else 0
        data["decisions"] = {
            "message": f"决策账本：{decision_count} 条决策，{outcome_count} 条结果追踪中",
        }
    else:
        data["decisions"] = {"message": "决策账本尚未启用"}

    return data


@router.get("/api/source")
async def api_source(path: str = Query(...), loc: str = Query(default="")):
    """Read a source file (absolute or relative path)."""
    resolved = _resolve_source_path(path)
    if not resolved.exists():
        return {"content": None, "error": f"File not found: {resolved}"}
    try:
        text = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return {"content": None, "error": str(e)}

    result: Dict[str, Any] = {"content": text, "line": None, "start": None, "end": None, "error": None}
    if loc:
        lines = text.split("\n")
        for i, l in enumerate(lines, 1):
            if loc in l:
                result["line"] = i
                result["start"] = max(1, i - 5)
                result["end"] = min(len(lines), i + 5)
                break
        if not result["line"]:
            result["error"] = f'loc "{loc}" not found in file'
            result["start"] = 1
            result["end"] = min(30, len(lines))
    return result


# ── static files ────────────────────────────────────────────────────────────


@router.get("/evolution_hub_style")
async def evolution_hub_style():
    """Serve the evolution hub style page."""
    p = _EVOLUTION_DIR / "evolution_hub_style.html"
    if not p.exists():
        raise HTTPException(404, "style page not found")
    return HTMLResponse(p.read_text(encoding="utf-8"), media_type="text/html")


@router.get("/architecture.svg")
async def architecture_svg():
    """Serve the architecture SVG."""
    p = _EVOLUTION_DIR / "architecture.svg"
    if not p.exists():
        raise HTTPException(404, "architecture SVG not found")
    return Response(p.read_bytes(), media_type="image/svg+xml")


@router.get("/api/architecture")
@cached(ttl=60)
def api_architecture():
    """Architecture node/connection data for the frontend SVG overlay."""
    # Return the same architecture data but with updated descriptions
    svg_path = _EVOLUTION_DIR / "architecture.svg"
    nodes: Dict[str, dict] = {}
    connections: list[dict] = []

    # Rebuild from the SVG if we can parse it, otherwise return static data
    if svg_path.exists():
        svg_text = svg_path.read_text(encoding="utf-8")
        # Extract node titles from text elements in the SVG
        for m in re.finditer(r'<text[^>]*>([^<]+)</text>', svg_text):
            name = m.group(1).strip()
            if name and 2 < len(name) < 50 and not name.startswith("http"):
                nodes[name] = {"desc": "", "src": ""}

    # If SVG parsing gave nothing, use a minimal set
    if not nodes:
        nodes = {
            "Cognitive OS": {"desc": "Decision-grade memory ledger. Evidence → Claim → Model → Decision → Intent → Outcome.", "src": ""},
            "Ledger": {"desc": "SQLite store with typed relations (supports_model, etc.).", "src": ""},
            "Reader": {"desc": "Semantic retrieval from Chroma vector index.", "src": ""},
            "Runtime": {"desc": "Dynamic model/statement/edge registration.", "src": ""},
            "Hermes Provider": {"desc": "Integration layer for Hermes agent context.", "src": "cognitive_os/hermes_provider.py"},
            "Chroma": {"desc": "Vector index for embedding-based recall.", "src": ""},
            "bge-m3": {"desc": "Local embedding model via Ollama (localhost:11434).", "src": ""},
            "Agent Context": {"desc": "Real-time auto-recall into Hermes session context.", "src": ""},
        }
        connections = [
            {"from": "Cognitive OS", "to": "Ledger"},
            {"from": "Cognitive OS", "to": "Reader"},
            {"from": "Reader", "to": "Chroma"},
            {"from": "Chroma", "to": "bge-m3"},
            {"from": "Hermes Provider", "to": "Cognitive OS"},
            {"from": "Hermes Provider", "to": "Agent Context"},
            {"from": "Runtime", "to": "Ledger"},
        ]

    return {"NODES": nodes, "CONNECTIONS": connections}


# ── register ──────────────────────────────────────────────────────────────

def register(app):
    """Called by Hermes Dashboard on plugin load."""
    app.include_router(router, prefix="/api/plugins/hermes-evolution-hub")
