"""
hermes-evolution-hub Dashboard plugin backend API.
Mounted at /api/plugins/hermes-evolution-hub/ by Hermes Dashboard (9119).

Target: Cognitive OS (decision-grade memory ledger).
"""
import functools
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Query
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

_COGNITIVE_OS_DB = Path(
    os.environ.get(
        "COGNITIVE_OS_DB",
        str(Path.home() / "projects" / "cognitive-os" / "data" / "cognitive.db"),
    )
)

DEFAULT_SOURCE_BASE = Path(os.environ.get("HERMES_SOURCE_BASE", str(Path(__file__).resolve().parents[3])))


def _resolve_source_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p
    if p.is_absolute():
        return p
    candidates: list[Path] = []
    if path.startswith("cognitive_os/"):
        project = Path.home() / "projects" / "cognitive-os"
        candidates.append(project / path)
    else:
        candidates.append(DEFAULT_SOURCE_BASE / path)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0] if candidates else DEFAULT_SOURCE_BASE / path


# ── TTL cache ──────────────────────────────────────────────────────────────
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


# ── SQLite helpers ─────────────────────────────────────────────────────────


def _query_db(sql: str, params: tuple = ()):
    try:
        conn = sqlite3.connect(str(_COGNITIVE_OS_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _row_count(table: str) -> int:
    rows = _query_db(f"SELECT COUNT(*) AS cnt FROM {table}")
    return rows[0]["cnt"] if rows else 0


def _table_exists(table: str) -> bool:
    rows = _query_db("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return bool(rows)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger():
    """Use the canonical Ledger for writes; the dashboard never owns its schema."""
    project = Path.home() / "projects" / "cognitive-os"
    if str(project) not in sys.path:
        sys.path.insert(0, str(project))
    from cognitive_os.store import Ledger
    return Ledger(_COGNITIVE_OS_DB)


def _clear_cache() -> None:
    _cache.clear()


def _query_readonly(sql: str, params: tuple = ()):
    """Read ledger data without allowing the dashboard to mutate it."""
    connection = sqlite3.connect(f"file:{_COGNITIVE_OS_DB.as_posix()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _as_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@router.get("/api/review")
@cached(ttl=5)
def api_review():
    """Human review queue for the Cognitive OS ledger; strictly read-only."""
    if not _COGNITIVE_OS_DB.exists():
        return {"source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(),
                "error": f"ledger not found: {_COGNITIVE_OS_DB}", "summary": {}, "queues": {}}
    try:
        now = datetime.now(timezone.utc)
        claims = [dict(row) for row in _query_readonly(
            "SELECT c.id, c.statement, c.kind, c.status, c.falsifier, "
            "COUNT(DISTINCT ce.evidence_id) AS evidence_count, "
            "COUNT(DISTINCT e.source_ref) AS source_count, "
            "GROUP_CONCAT(DISTINCT e.source_ref) AS source_refs "
            "FROM claims c LEFT JOIN claim_evidence ce ON ce.claim_id=c.id "
            "LEFT JOIN evidence e ON e.id=ce.evidence_id "
            "GROUP BY c.id ORDER BY c.rowid DESC LIMIT 24"
        )]
        decisions = []
        for row in _query_readonly(
            "SELECT d.id, d.question, d.selected_option, d.core_bet, d.falsifiers_json, d.review_at, d.status, "
            "COUNT(DISTINCT dc.claim_id) AS claim_count, COUNT(DISTINCT o.id) AS outcome_count, "
            "SUM(CASE WHEN o.implication='contradicts' THEN 1 ELSE 0 END) AS contradiction_count "
            "FROM decisions d LEFT JOIN decision_claims dc ON dc.decision_id=d.id "
            "LEFT JOIN outcomes o ON o.decision_id=d.id GROUP BY d.id ORDER BY d.rowid DESC LIMIT 18"
        ):
            item = dict(row)
            review_at = _as_utc(item.get("review_at", ""))
            item["review_state"] = "overdue" if review_at and review_at < now and item.get("status") == "active" else "scheduled"
            item["contradiction_count"] = int(item.get("contradiction_count") or 0)
            decisions.append(item)
        models = []
        for row in _query_readonly(
            "SELECT m.id, m.proposition, m.status, COUNT(DISTINCT r.source_id) AS support_claim_count, "
            "COUNT(DISTINCT e.source_ref) AS support_source_count FROM models m "
            "LEFT JOIN object_relations r ON r.target_type='model' AND r.target_id=m.id "
            "AND r.source_type='claim' AND r.key='supports_model' "
            "LEFT JOIN claim_evidence ce ON ce.claim_id=r.source_id LEFT JOIN evidence e ON e.id=ce.evidence_id "
            "GROUP BY m.id ORDER BY m.rowid DESC LIMIT 12"
        ):
            item = dict(row)
            item["admission_state"] = "ready" if item["support_claim_count"] >= 2 and item["support_source_count"] >= 2 else "insufficient_support"
            models.append(item)
        intents = []
        for row in _query_readonly("SELECT id, action, trigger_kind, trigger_value, valid_until, status FROM intents ORDER BY rowid DESC LIMIT 18"):
            item = dict(row)
            expiry = _as_utc(item.get("valid_until", ""))
            item["expiry_state"] = "expired" if expiry and expiry < now and item.get("status") == "active" else "valid"
            intents.append(item)
        outcomes = [dict(row) for row in _query_readonly(
            "SELECT id, decision_id, observation, implication, observed_at FROM outcomes ORDER BY observed_at DESC LIMIT 18"
        )]
        issues = []
        proposals = []
        if _table_exists("maintenance_issues"):
            issues = [dict(row) for row in _query_readonly(
                "SELECT id, kind, severity, target_type, target_id, detail_json, detected_at FROM maintenance_issues "
                "WHERE resolved_at IS NULL ORDER BY detected_at DESC LIMIT 12"
            )]
        if _table_exists("proposals"):
            proposals = [dict(row) for row in _query_readonly(
                "SELECT id, kind, target_type, target_id, suggested_action, rationale, created_at FROM proposals "
                "WHERE status='pending' ORDER BY created_at DESC LIMIT 12"
            )]
        summary = {
            "evidence": _row_count("evidence"), "claims": _row_count("claims"), "decisions": _row_count("decisions"), "outcomes": _row_count("outcomes"),
            "unbacked_claims": sum(1 for x in claims if not x["evidence_count"]),
            "unfalsifiable_claims": sum(1 for x in claims if not str(x.get("falsifier") or "").strip()),
            "overdue_decisions": sum(1 for x in decisions if x["review_state"] == "overdue"),
            "expired_intents": sum(1 for x in intents if x["expiry_state"] == "expired"),
            "contradictions": sum(1 for x in outcomes if x.get("implication") == "contradicts"),
            "weak_models": sum(1 for x in models if x["admission_state"] == "insufficient_support"),
            "pending_issues": len(issues), "pending_proposals": len(proposals),
        }
        return {"source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(), "error": None, "summary": summary,
                "queues": {"claims": claims, "decisions": decisions, "models": models, "intents": intents,
                           "outcomes": outcomes, "issues": issues, "proposals": proposals}}
    except Exception as error:
        return {"source": "Cognitive OS SQLite Ledger", "as_of": _now_iso(),
                "error": f"{type(error).__name__}: {error}", "summary": {}, "queues": {}}


# ── API endpoints ─────────────────────────────────────────────────────────


@router.get("/api/health")
@cached(ttl=5)
def api_health():
    data: Dict[str, Any] = {}
    db_ok = _COGNITIVE_OS_DB.exists()
    if db_ok:
        object_count = sum(
                _row_count(t) for t in ["evidence", "claims", "models", "decisions", "intents", "outcomes"]
                if _table_exists(t)
            )
        data["ledger"] = {"status": "ready" if _table_exists("claims") else "empty", "object_count": object_count}
        data["server"] = {"vdb": "ok" if _table_exists("claims") else "empty", "vdb_points": object_count}
    else:
        data["ledger"] = {"status": "down", "object_count": 0}
        data["server"] = {"vdb": "down", "vdb_points": 0}

    meta_1h: dict[str, int] = {}
    for table, label in [
        ("evidence", "Evidence"), ("claims", "Claim"), ("models", "Model"),
        ("decisions", "Decision"), ("intents", "Intent"), ("outcomes", "Outcome"),
        ("object_relations", "Relation"),
    ]:
        if _table_exists(table):
            rows = _query_db(f"SELECT COUNT(*) AS cnt FROM {table} ORDER BY rowid DESC LIMIT 30")
            meta_1h[label] = rows[0]["cnt"] if rows else 0
    data["pipeline_1h"] = meta_1h

    try:
        r = subprocess.run(
            ["grep", "-E", "prefetch|memory_search|memory_add", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        recent = r.stdout.strip().split("\n")[-30:]
        data["prefetch"] = {"ok": sum(1 for l in recent if l), "fail": 0}
    except Exception:
        data["prefetch"] = {"ok": 0, "fail": 0}
    return data


@router.get("/api/agent-loop")
@cached(ttl=5)
def api_agent_loop():
    try:
        r = subprocess.run(["tail", "-500", str(_AGENT_LOG)], capture_output=True, text=True, timeout=3)
    except Exception:
        return {"total_api": 0, "total_tool": 0, "avg_latency": 0,
                "total_tokens_in": 0, "total_tokens_out": 0, "tool_errors": 0,
                "api_calls": [], "tool_calls": []}
    lines = r.stdout.strip().split("\n")
    api, tools = [], []
    token_in, token_out, total_latency, api_count, tool_errors = 0, 0, 0, 0, 0
    for line in lines[-200:]:
        if "API call" in line:
            api.append(line[-120:])
            api_count += 1
            m = re.search(r"latency=([\d.]+)", line)
            if m: total_latency += float(m.group(1))
            m = re.search(r"tokens=(\d+)\+(\d+)", line)
            if m:
                token_in += int(m.group(1))
                token_out += int(m.group(2))
        if "Tool call" in line or "tool_call" in line:
            tools.append(line[-120:])
        if "tool error" in line.lower() or "ToolError" in line:
            tool_errors += 1
    return {
        "total_api": api_count, "total_tool": len(tools),
        "avg_latency": round(total_latency / api_count, 2) if api_count else 0,
        "total_tokens_in": token_in, "total_tokens_out": token_out,
        "tool_errors": tool_errors, "api_calls": api[-10:], "tool_calls": tools[-10:],
    }


@router.get("/api/stats")
@cached(ttl=10)
def api_stats():
    data: Dict[str, Any] = {}
    for t in ["evidence", "claims", "models", "decisions", "intents", "outcomes"]:
        data[t] = _row_count(t) if _table_exists(t) else 0
    data["relation_types"] = {}
    if _table_exists("relation_types"):
        rows = _query_db("SELECT key, source_type, target_type, description FROM relation_types")
        data["relation_types"] = {r["key"]: {"source": r["source_type"], "target": r["target_type"]} for r in rows}
    data["relations_by_type"] = {}
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, COUNT(*) AS cnt FROM object_relations GROUP BY key")
        data["relations_by_type"] = {r["key"]: r["cnt"] for r in rows}
        data["total_relations"] = sum(data["relations_by_type"].values())
    if _table_exists("claims"):
        rows = _query_db("SELECT status, COUNT(*) AS cnt FROM claims GROUP BY status")
        data["claim_status"] = {r["status"]: r["cnt"] for r in rows}
    return data


@router.get("/api/evolution")
@cached(ttl=15)
def api_evolution():
    steps = []
    for table, label in [
        ("evidence", "Evidence"), ("claims", "Claim"), ("models", "Model"),
        ("decisions", "Decision"), ("intents", "Intent"), ("outcomes", "Outcome"),
    ]:
        if not _table_exists(table):
            continue
        rows = _query_db(f"SELECT id FROM {table} ORDER BY rowid DESC LIMIT 5")
        for r in rows:
            steps.append({"layer": f"ledger/{label}", "id": r["id"], "time": _now_iso(), "type": label})
    return {"steps": steps[:20]}


@router.get("/api/timeline")
@cached(ttl=5)
def api_timeline():
    items = []
    for table, label, content_col in [
        ("evidence", "Evidence", "content"), ("claims", "Claim", "statement"),
        ("models", "Model", "proposition"), ("decisions", "Decision", "question"),
        ("intents", "Intent", "action"), ("outcomes", "Outcome", "observation"),
    ]:
        if not _table_exists(table):
            continue
        rows = _query_db(f"SELECT id, {content_col} AS txt FROM {table} ORDER BY rowid DESC LIMIT 5")
        for r in rows:
            items.append({"id": r["id"], "content": (r["txt"] or "")[:100], "type": label, "time": _now_iso()})
    items.sort(key=lambda x: x.get("time", ""), reverse=True)
    return {"items": items[:20]}


@router.get("/api/memory-feed")
@cached(ttl=5)
def api_memory_feed():
    layers = ["Evidence", "Claim", "Model", "Decision", "Intent", "Outcome"]
    recent = []
    for layer, table, content_col in [
        ("Evidence", "evidence", "content"), ("Claim", "claims", "statement"),
        ("Model", "models", "proposition"), ("Decision", "decisions", "question"),
        ("Intent", "intents", "action"), ("Outcome", "outcomes", "observation"),
    ]:
        if not _table_exists(table):
            continue
        if table in ("evidence", "outcomes"):
            rows = _query_db(f"SELECT id, {content_col} AS txt, observed_at AS ts FROM {table} ORDER BY observed_at DESC LIMIT 5")
        else:
            rows = _query_db(f"SELECT id, {content_col} AS txt FROM {table} ORDER BY rowid DESC LIMIT 5")
        for r in rows:
            recent.append({"layer": layer, "time": r["ts"] if "ts" in r.keys() else "", "op": "ADD", "summary": (r["txt"] or "")[:120], "id": r["id"]})
    return {"layers": layers, "recent": recent, "total": len(recent)}


@router.get("/api/prefetch-feed")
@cached(ttl=5)
def api_prefetch_feed():
    try:
        rows = [dict(row) for row in _query_readonly(
            "SELECT occurred_at AS time, mode, query_preview AS query, hit_count AS hits, latency_ms, status, error "
            "FROM recall_events ORDER BY occurred_at DESC LIMIT 30"
        )]
        stats = {"auto_recall": sum(1 for row in rows if row["mode"] == "auto_recall"),
                 "memory_search": sum(1 for row in rows if row["mode"] == "memory_search"),
                 "errors": sum(1 for row in rows if row["status"] != "success")}
        return {"recent": rows, "stats": stats, "source": "Cognitive OS recall_events"}
    except Exception as error:
        return {"recent": [], "stats": {}, "source": "Cognitive OS recall_events", "error": f"{type(error).__name__}: {error}"}


@router.get("/api/self-improvement")
@cached(ttl=5)
def api_self_improvement():
    data: Dict[str, Any] = {}
    memory_updates: Dict[str, str] = {}
    for name in ["MEMORY.md", "USER.md"]:
        p = _HERMES_HOME / name
        if p.exists():
            memory_updates[name] = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
    data["memory_updates"] = memory_updates
    recent_skills = []
    skills_dir = _HERMES_HOME / "skills"
    if skills_dir.exists():
        try:
            r = subprocess.run(
                ["find", str(skills_dir), "-name", "SKILL.md", "-newer", str(_COGNITIVE_OS_DB)],
                capture_output=True, text=True, timeout=3,
            )
            for path in r.stdout.strip().split("\n"):
                if not path.strip(): continue
                p = Path(path.strip())
                recent_skills.append({
                    "name": p.parent.name,
                    "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
                })
        except Exception:
            pass
    data["recent_skills"] = recent_skills[:10]
    try:
        r = subprocess.run(
            ["grep", "-E", "memory_add|memory_search|skill_manage", str(_AGENT_LOG)],
            capture_output=True, text=True, timeout=3,
        )
        tool_lines = r.stdout.strip().split("\n")[-10:]
        data["recent_tool_calls"] = [
            {"tool": "memory", "action": "add/search/manage", "summary": line[-80:], "time": _now_iso()}
            for line in tool_lines if line.strip()
        ]
    except Exception:
        data["recent_tool_calls"] = []
    return data


@router.get("/api/cognitive-quality")
@cached(ttl=5)
def api_cognitive_quality():
    latest: Dict[str, Any] = {}
    health: Dict[str, Any] = {}
    recent_ops: list[dict] = []
    edge_counts: Dict[str, int] = {}
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, COUNT(*) AS cnt FROM object_relations GROUP BY key")
        edge_counts = {r["key"]: r["cnt"] for r in rows}
    latest["edge_type_counts"] = edge_counts
    health["edge_type_counts"] = edge_counts
    evidence_count = _row_count("evidence") if _table_exists("evidence") else 0
    claim_count = _row_count("claims") if _table_exists("claims") else 0
    model_count = _row_count("models") if _table_exists("models") else 0
    decision_count = _row_count("decisions") if _table_exists("decisions") else 0
    total_edges = sum(edge_counts.values())
    health["schema_total"] = claim_count + model_count + decision_count
    health["memory_edge_total"] = total_edges
    health["cognitive_edge_total"] = total_edges
    health["related_to_ratio"] = 0.0
    orphan_schema = 0
    if _table_exists("claims") and _table_exists("claim_evidence"):
        rows = _query_db(
            "SELECT COUNT(*) AS cnt FROM claims c "
            "WHERE NOT EXISTS (SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id)"
        )
        orphan_schema = rows[0]["cnt"] if rows else 0
    health["orphan_schema_count"] = orphan_schema
    health["no_evidence_schema_count"] = orphan_schema
    latest["schema_created"] = claim_count + model_count + decision_count
    latest["schema_reused"] = 0
    latest["evidence_added"] = evidence_count
    latest["edges_created"] = total_edges
    latest["related_to_ratio"] = 0.0
    latest["warnings"] = []
    if orphan_schema:
        latest["warnings"].append(f"{orphan_schema} claims without evidence")
    if _table_exists("object_relations"):
        rows = _query_db("SELECT key, source_type FROM object_relations ORDER BY rowid DESC LIMIT 5")
        for r in rows:
            recent_ops.append({"time": _now_iso(), "op": "RELATION", "edge_type": r["key"]})
    health["graph_ops"] = {"total": total_edges}
    return {"latest": latest, "reports": [], "health": health, "recent_ops": recent_ops}


@router.get("/api/decision-workspace")
@cached(ttl=5)
def api_decision_workspace():
    data: Dict[str, Any] = {}
    data["source"] = {
        "vdb_total": _row_count("evidence") if _table_exists("evidence") else 0,
        "graph_total": _row_count("claims") if _table_exists("claims") else 0,
    }
    health: Dict[str, Any] = {}
    health["schema_total"] = (_row_count("claims") if _table_exists("claims") else 0) \
        + (_row_count("models") if _table_exists("models") else 0) \
        + (_row_count("decisions") if _table_exists("decisions") else 0)
    health["memory_edge_total"] = _row_count("object_relations") if _table_exists("object_relations") else 0
    health["cognitive_edge_total"] = health["memory_edge_total"]
    orphan = 0
    if _table_exists("claims") and _table_exists("claim_evidence"):
        rows = _query_db(
            "SELECT COUNT(*) AS cnt FROM claims c "
            "WHERE NOT EXISTS (SELECT 1 FROM claim_evidence ce WHERE ce.claim_id = c.id)"
        )
        orphan = rows[0]["cnt"] if rows else 0
    health["orphan_schema_count"] = orphan
    data["graph_health"] = health
    claims_items = []
    if _table_exists("claims"):
        rows = _query_db("SELECT id, statement, status, kind FROM claims ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            claims_items.append({"id": r["id"], "time": _now_iso(), "content": (r["statement"] or "")[:120],
                                 "status": r["status"], "tags": [r["kind"]]})
    data["claims"] = {"source": "Cognitive OS Ledger", "items": claims_items}
    models_items = []
    if _table_exists("models"):
        rows = _query_db("SELECT id, proposition, status FROM models ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            models_items.append({"id": r["id"], "time": _now_iso(), "content": (r["proposition"] or "")[:120],
                                 "status": r["status"]})
    data["models"] = {"source": "Cognitive OS Ledger", "items": models_items}
    contracts_items = []
    if _table_exists("decisions"):
        rows = _query_db("SELECT id, question, selected_option, status FROM decisions ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            contracts_items.append({"id": r["id"], "time": _now_iso(),
                                    "content": f"Q: {(r['question'] or '')[:80]} \u2192 {r['selected_option']}",
                                    "status": r["status"]})
    data["contracts"] = {"source": "Decision Ledger", "items": contracts_items}
    intent_items = []
    if _table_exists("intents"):
        rows = _query_db("SELECT id, action, status, valid_until FROM intents ORDER BY rowid DESC LIMIT 6")
        for r in rows:
            intent_items.append({"id": r["id"], "time": r["valid_until"] or _now_iso(),
                                 "content": (r["action"] or "")[:120], "status": r["status"],
                                 "tags": [f"until {r['valid_until'][:10]}" if r["valid_until"] else ""]})
    data["intents"] = {"source": "Intent Ledger", "items": intent_items}
    if _table_exists("decisions"):
        dc = _row_count("decisions")
        oc = _row_count("outcomes") if _table_exists("outcomes") else 0
        data["decisions"] = {"message": f"决策账本：{dc} 条决策，{oc} 条结果追踪中"}
    else:
        data["decisions"] = {"message": "决策账本尚未启用"}
    return data


def _topic_detail(topic_id: str) -> dict[str, Any]:
    members = _query_readonly("SELECT object_type, object_id FROM topic_members WHERE topic_id=?", (topic_id,))
    by_type: dict[str, set[str]] = {}
    for member in members:
        by_type.setdefault(member["object_type"], set()).add(member["object_id"])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    labels = {
        "evidence": ("evidence", "content", "status"), "claim": ("claims", "statement", "status"),
        "model": ("models", "proposition", "status"), "decision": ("decisions", "question", "status"),
        "intent": ("intents", "action", "status"), "outcome": ("outcomes", "observation", "implication"),
    }
    for kind, ids in by_type.items():
        if kind not in labels or not ids:
            continue
        table, field, state_field = labels[kind]
        marks = ",".join("?" for _ in ids)
        if kind == "evidence":
            rows = _query_readonly(
                f"SELECT e.id, e.content AS label, COALESCE(es.status, 'active') AS status "
                f"FROM evidence e LEFT JOIN evidence_state es ON es.evidence_id=e.id WHERE e.id IN ({marks})", tuple(ids)
            )
        else:
            rows = _query_readonly(f"SELECT id, {field} AS label, {state_field} AS status FROM {table} WHERE id IN ({marks})", tuple(ids))
        for row in rows:
            nodes.append({"id": row["id"], "kind": kind, "label": str(row["label"])[:92], "status": row["status"] if "status" in row.keys() else ""})
    node_ids = {node["id"] for node in nodes}
    # Suggested topics are often Evidence-only.  Follow explicit ledger links
    # one hop so Focus shows the related judgement/decision as context rather
    # than presenting a disconnected pile of source material.
    if by_type.get("evidence"):
        marks = ",".join("?" for _ in by_type["evidence"])
        linked_claims = _query_readonly(
            f"SELECT c.id, c.statement AS label, c.status, ce.evidence_id FROM claims c "
            f"JOIN claim_evidence ce ON ce.claim_id=c.id WHERE ce.evidence_id IN ({marks})", tuple(by_type["evidence"])
        )
        for row in linked_claims:
            if row["id"] not in node_ids:
                nodes.append({"id": row["id"], "kind": "claim", "label": str(row["label"])[:92], "status": row["status"], "membership": "context"})
                node_ids.add(row["id"])
            edges.append({"from": row["evidence_id"], "to": row["id"], "label": "依据", "membership": "context"})
            by_type.setdefault("claim", set()).add(row["id"])
    if by_type.get("claim"):
        marks = ",".join("?" for _ in by_type["claim"])
        for row in _query_readonly(f"SELECT evidence_id, claim_id FROM claim_evidence WHERE claim_id IN ({marks})", tuple(by_type["claim"])):
            if row["evidence_id"] in node_ids:
                edges.append({"from": row["evidence_id"], "to": row["claim_id"], "label": "依据"})
        decision_links = _query_readonly(f"SELECT decision_id, claim_id FROM decision_claims WHERE claim_id IN ({marks})", tuple(by_type["claim"]))
        decision_ids = {row["decision_id"] for row in decision_links if row["decision_id"] not in node_ids}
        if decision_ids:
            decision_marks = ",".join("?" for _ in decision_ids)
            for detail in _query_readonly(f"SELECT id, question AS label, status FROM decisions WHERE id IN ({decision_marks})", tuple(decision_ids)):
                nodes.append({"id": detail["id"], "kind": "decision", "label": str(detail["label"])[:92], "status": detail["status"], "membership": "context"})
                node_ids.add(detail["id"])
        for row in decision_links:
            if row["decision_id"] in node_ids:
                edges.append({"from": row["claim_id"], "to": row["decision_id"], "label": "支撑", "membership": "context"})
    if by_type.get("decision"):
        marks = ",".join("?" for _ in by_type["decision"])
        for row in _query_readonly(f"SELECT id, decision_id FROM intents WHERE decision_id IN ({marks})", tuple(by_type["decision"])):
            if row["id"] in node_ids:
                edges.append({"from": row["decision_id"], "to": row["id"], "label": "行动"})
        for row in _query_readonly(f"SELECT id, decision_id FROM outcomes WHERE decision_id IN ({marks})", tuple(by_type["decision"])):
            if row["id"] in node_ids:
                edges.append({"from": row["decision_id"], "to": row["id"], "label": "反馈"})
    return {"nodes": nodes, "edges": edges}


@router.get("/api/topic-map")
@cached(ttl=3)
def api_topic_map():
    """Semantic overview: a topic is the primary visual unit, ledger types are detail."""
    try:
        topics = []
        for row in _query_readonly(
            "SELECT t.id, t.label, t.summary, t.status, t.created_by, t.created_at, COUNT(tm.object_id) AS member_count "
            "FROM topics t LEFT JOIN topic_members tm ON tm.topic_id=t.id GROUP BY t.id ORDER BY member_count DESC, t.created_at DESC"
        ):
            detail = _topic_detail(row["id"])
            contradiction = sum(1 for node in detail["nodes"] if node["kind"] == "outcome" and node["status"] == "contradicts")
            topics.append({**dict(row), "attention": contradiction, "detail": detail})
        unclassified = _query_readonly(
            "SELECT COALESCE(es.status, 'active') AS status, COUNT(*) AS count FROM evidence e "
            "LEFT JOIN evidence_state es ON es.evidence_id=e.id "
            "WHERE e.id NOT IN (SELECT object_id FROM topic_members WHERE object_type='evidence') GROUP BY COALESCE(es.status, 'active')"
        )
        recent_events = [dict(row) for row in _query_readonly(
            "SELECT occurred_at, event_type, object_type, object_id, reason FROM cognitive_events "
            "WHERE event_type NOT IN ('topic_member_added', 'topic_suggested', 'topic_batch_cleared') "
            "ORDER BY occurred_at DESC LIMIT 8"
        )]
        inbox = {row["status"]: int(row["count"]) for row in unclassified}
        return {"source": "Cognitive OS", "topics": topics, "unclassified": inbox, "recent_events": recent_events}
    except Exception as error:
        return {"source": "Cognitive OS", "topics": [], "unclassified": {}, "recent_events": [], "error": f"{type(error).__name__}: {error}"}


@router.post("/api/corrections")
def api_corrections(payload: dict[str, Any] = Body(...)):
    """Explicit user correction.  History stays intact and ordinary retrieval honors it."""
    object_type = str(payload.get("object_type", ""))
    object_id = str(payload.get("object_id", ""))
    action = str(payload.get("action", ""))
    reason = str(payload.get("reason", "")).strip()
    if not object_id or not reason:
        raise HTTPException(400, "object_id and correction reason are required")
    ledger = _ledger()
    try:
        if object_type == "claim":
            current = ledger.object_summary("claim", object_id)
            if not current:
                raise ValueError("claim does not exist")
            status = {"verify": "active", "wrong": "challenged", "outdated": "superseded", "revise": str(payload.get("status") or "proposed")}.get(action)
            if not status:
                raise ValueError("unsupported claim correction")
            statement = str(payload.get("statement") or current["statement"])
            ledger.revise_claim(object_id, statement=statement, status=status, created_by="dashboard_user")
            ledger._record_event("user_correction", "claim", object_id, "dashboard_user", reason=reason, payload={"action": action})
            ledger._connection.commit()
        elif object_type == "evidence":
            state = {"verify": "active", "wrong": "retracted", "outdated": "contested"}.get(action)
            if not state:
                raise ValueError("unsupported evidence correction")
            ledger.set_evidence_state(object_id, status=state, reason=reason, changed_by="dashboard_user")
        elif object_type == "topic" and action == "rename":
            ledger.rename_topic(object_id, label=str(payload.get("label", "")), summary=str(payload.get("summary", "")), changed_by="dashboard_user")
        else:
            raise ValueError("unsupported correction target")
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    finally:
        ledger.close()
    _clear_cache()
    return {"ok": True, "object_type": object_type, "object_id": object_id}


@router.get("/api/relationship-map")
@cached(ttl=5)
def api_relationship_map():
    """Return a small, decision-centred map of the ledger's explicit relations."""
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []

    def add_node(node_id: str, kind: str, label: str, status: str = "") -> None:
        nodes[node_id] = {"id": node_id, "kind": kind, "label": label[:72], "status": status}

    try:
        decision_rows = _query_db("SELECT id, question, status FROM decisions ORDER BY rowid DESC LIMIT 1")
        if not decision_rows:
            claim_rows = _query_db("SELECT id, statement, status FROM claims ORDER BY rowid DESC LIMIT 6")
            claim_ids = [row["id"] for row in claim_rows]
            for row in claim_rows:
                add_node(row["id"], "claim", row["statement"], row["status"])
            if claim_ids:
                marks = ",".join("?" for _ in claim_ids)
                evidence_rows = _query_db(
                    f"SELECT e.id, e.content, e.source_ref, ce.claim_id FROM evidence e "
                    f"JOIN claim_evidence ce ON ce.evidence_id=e.id WHERE ce.claim_id IN ({marks})",
                    tuple(claim_ids),
                )
                for row in evidence_rows:
                    add_node(row["id"], "evidence", row["content"], row["source_ref"])
                    edges.append({"from": row["id"], "to": row["claim_id"], "label": "支撑"})
            return {"source": "Cognitive OS", "focus": "recent_claims", "nodes": list(nodes.values()), "edges": edges}

        decision = decision_rows[0]
        decision_id = decision["id"]
        add_node(decision_id, "decision", decision["question"], decision["status"])
        claim_rows = _query_db(
            "SELECT c.id, c.statement, c.status FROM claims c JOIN decision_claims dc ON dc.claim_id=c.id "
            "WHERE dc.decision_id=? ORDER BY c.rowid", (decision_id,)
        )
        claim_ids = [row["id"] for row in claim_rows]
        for row in claim_rows:
            add_node(row["id"], "claim", row["statement"], row["status"])
            edges.append({"from": row["id"], "to": decision_id, "label": "作为依据"})
        if claim_ids:
            marks = ",".join("?" for _ in claim_ids)
            evidence_rows = _query_db(
                f"SELECT e.id, e.content, e.source_ref, ce.claim_id FROM evidence e "
                f"JOIN claim_evidence ce ON ce.evidence_id=e.id WHERE ce.claim_id IN ({marks})",
                tuple(claim_ids),
            )
            for row in evidence_rows:
                add_node(row["id"], "evidence", row["content"], row["source_ref"])
                edges.append({"from": row["id"], "to": row["claim_id"], "label": "支撑"})
            model_rows = _query_db(
                f"SELECT m.id, m.proposition, m.status, r.source_id FROM models m "
                f"JOIN object_relations r ON r.target_id=m.id WHERE r.source_type='claim' "
                f"AND r.target_type='model' AND r.key='supports_model' AND r.source_id IN ({marks})",
                tuple(claim_ids),
            )
            for row in model_rows:
                add_node(row["id"], "model", row["proposition"], row["status"])
                edges.append({"from": row["source_id"], "to": row["id"], "label": "支持模型"})
        for row in _query_db("SELECT id, action, status FROM intents WHERE decision_id=? ORDER BY rowid", (decision_id,)):
            add_node(row["id"], "intent", row["action"], row["status"])
            edges.append({"from": decision_id, "to": row["id"], "label": "产生行动"})
        for row in _query_db("SELECT id, observation, implication FROM outcomes WHERE decision_id=? ORDER BY observed_at", (decision_id,)):
            add_node(row["id"], "outcome", row["observation"], row["implication"])
            edges.append({"from": decision_id, "to": row["id"], "label": "现实反馈"})
        return {"source": "Cognitive OS", "focus": decision_id, "nodes": list(nodes.values()), "edges": edges}
    except Exception as error:
        return {"source": "Cognitive OS", "focus": None, "nodes": [], "edges": [], "error": f"{type(error).__name__}: {error}"}


@router.get("/api/category-overview")
@cached(ttl=5)
def api_category_overview():
    """A compact map of what is stored and which explicit relations exist."""
    categories = [
        ("evidence", "证据", "evidence"), ("claim", "主张", "claims"),
        ("model", "模型", "models"), ("decision", "决策", "decisions"),
        ("intent", "行动承诺", "intents"), ("outcome", "结果", "outcomes"),
        ("proposal", "待审提案", "proposals"),
    ]
    try:
        nodes = []
        for kind, label, table in categories:
            count = _row_count(table) if _table_exists(table) else 0
            nodes.append({"id": kind, "kind": kind, "label": label, "count": count, "status": ""})
        relation_specs = [
            ("evidence", "claim", "支撑", "SELECT COUNT(*) AS cnt FROM claim_evidence"),
            ("claim", "model", "支持模型", "SELECT COUNT(*) AS cnt FROM object_relations WHERE source_type='claim' AND target_type='model' AND key='supports_model'"),
            ("claim", "decision", "作为依据", "SELECT COUNT(*) AS cnt FROM decision_claims"),
            ("decision", "intent", "产生行动", "SELECT COUNT(*) AS cnt FROM intents"),
            ("decision", "outcome", "得到结果", "SELECT COUNT(*) AS cnt FROM outcomes"),
        ]
        edges = []
        for source, target, label, sql in relation_specs:
            rows = _query_db(sql)
            count = int(rows[0]["cnt"]) if rows else 0
            if count:
                edges.append({"from": source, "to": target, "label": f"{label} × {count}"})
        return {"source": "Cognitive OS", "nodes": nodes, "edges": edges, "error": None}
    except Exception as error:
        return {"source": "Cognitive OS", "nodes": [], "edges": [], "error": f"{type(error).__name__}: {error}"}


@router.get("/api/source")
async def api_source(path: str = Query(...), loc: str = Query(default="")):
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
            result["error"] = f'loc "{loc}" not found'
            result["start"] = 1
            result["end"] = min(30, len(lines))
    return result


# ── static files ────────────────────────────────────────────────────────────


@router.get("/evolution_hub_style")
async def evolution_hub_style():
    p = _EVOLUTION_DIR / "evolution_hub_style.html"
    if not p.exists():
        raise HTTPException(404, "style page not found")
    return HTMLResponse(p.read_text(encoding="utf-8"), media_type="text/html")


@router.get("/architecture.svg")
async def architecture_svg():
    p = _EVOLUTION_DIR / "architecture.svg"
    if not p.exists():
        raise HTTPException(404, "architecture SVG not found")
    return Response(p.read_bytes(), media_type="image/svg+xml")


_COGNITIVE_NODE_OVERRIDES = {
    "MemAgent": {"label": "证据提炼", "file": None, "loc": None,
                 "desc": "Cognitive OS 的证据入口。对话与显式记录先作为 Evidence 保留；它们不会自动成为事实、主张或模型。"},
    "Reconciler": {"label": "主张校验", "file": None, "loc": None,
                   "desc": "Claim 的人工审查边界。主张必须关联 Evidence 并写明证伪条件；修订保留历史，不以自动总结覆盖旧判断。"},
    "记忆检索": {"label": "认知检索", "file": None, "loc": None,
                 "desc": "Cognitive Reader 按查询检索 Evidence 与 Claim，并带回关联的 Model、Decision、Intent 上下文。检索命中不是被系统采纳的真相。"},
    "记忆写入": {"label": "证据记录", "file": None, "loc": None,
                 "desc": "显式写入只创建 Evidence，并保存来源、观察时间与创建者。一次对话不会自动提升为 Claim、Model 或 Decision。"},
    "System 2 Writer": {"label": "维护扫描", "file": None, "loc": None,
                        "desc": "Maintenance Scanner 发现待复核项：证据不足、缺失证伪条件、逾期决策、过期 Intent 与矛盾 Outcome。它只生成审查信号或提案，不自动改写账本。"},
    "L1_RAW": {"label": "Evidence", "file": None, "loc": None,
               "desc": "不可变的证据记录：内容、来源、观察时间与创建者。Evidence 是判断的依据，不是系统自动认定的结论。"},
    "L2_FACT": {"label": "Claim", "file": None, "loc": None,
                "desc": "可证伪的主张，可为事实、判断、假设或约束。每条 Claim 都应关联 Evidence，并写明什么情况会推翻它。"},
    "L3_SUMMARY": {"label": "提案队列", "file": None, "loc": None,
                   "desc": "维护扫描产生的待审查提案。提案不会自动变成主张、模型或决策，必须由人确认、拒绝或暂缓。"},
    "L4_IDENTITY": {"label": "Decision", "file": None, "loc": None,
                    "desc": "决策账本：记录问题、备选项、所选方案、关联主张、核心押注、证伪条件与复盘时间。"},
    "L5_KNOWLEDGE": {"label": "Model", "file": None, "loc": None,
                     "desc": "可迁移的因果机制。Model 具有命题、适用范围、机制与失效条件；激活前需要来自至少两个独立来源的支持。"},
    "L6_SCHEMA": {"label": "模型修订", "file": None, "loc": None,
                  "desc": "Model 的修订轨迹。模型被新证据挑战时保留原版本，显式记录被削弱、退休或更新，而不是静默覆盖。"},
    "L7_INTENTION": {"label": "Intent", "file": None, "loc": None,
                     "desc": "由 Decision 创建的执行承诺，包含动作、触发条件、有效期和状态。它是可审查的行动队列，不是自动提醒。"},
    "System 1 Writer": {"label": "回合缓冲", "file": None, "loc": None,
                        "desc": "Hermes Provider 的回合缓冲。对话可按策略写成 Evidence，但不会由后台自动抽取并接受 Claim 或 Model。"},
}

_COGNITIVE_SOURCE_LOCATIONS = {
    "MemAgent": ("cognitive_os/hermes_provider.py", "sync_turn"),
    "Reconciler": ("cognitive_os/store.py", "revise_claim"),
    "\u8bb0\u5fc6\u68c0\u7d22": ("cognitive_os/reader.py", "CognitiveReader"),
    "\u8bb0\u5fc6\u5199\u5165": ("cognitive_os/hermes_provider.py", "_add_explicit_evidence"),
    "System 2 Writer": ("cognitive_os/maintenance.py", "MaintenanceScanner"),
    "L1_RAW": ("cognitive_os/store.py", "create_evidence"),
    "L2_FACT": ("cognitive_os/store.py", "create_claim"),
    "L3_SUMMARY": ("cognitive_os/maintenance_llm.py", "MaintenanceProposalAuthor"),
    "L4_IDENTITY": ("cognitive_os/store.py", "create_decision"),
    "L5_KNOWLEDGE": ("cognitive_os/store.py", "create_model"),
    "L6_SCHEMA": ("cognitive_os/store.py", "revise_model"),
    "L7_INTENTION": ("cognitive_os/store.py", "create_intent"),
    "System 1 Writer": ("cognitive_os/hermes_provider.py", "_flush_turn_buffer_locked"),
}

_COGNITIVE_STORAGE_OVERRIDES = {
    "Vector DB": {
        "label": "向量索引 DB", "file": "cognitive_os/retrieval.py", "loc": "SqliteVectorIndex",
        "desc": "检索加速器：C:/Users/CYF/projects/cognitive-os/data/cognitive.vectors.db。仅保存 Evidence / Claim 的向量索引，语义真相仍在账本数据库。",
    },
    "Graph DB": {
        "label": "账本数据库", "file": "cognitive_os/store.py", "loc": "Ledger",
        "desc": "语义真相：C:/Users/CYF/projects/cognitive-os/data/cognitive.db。保存 Evidence、Claim、Model、Decision、Intent、Outcome、关系与审计事件。",
    },
    "SQLite Session": {
        "label": "Kuzu 投影", "file": "cognitive_os/graph.py", "loc": "KuzuProjection",
        "desc": "可重建图投影：C:/Users/CYF/projects/cognitive-os/data/cognitive.kuzu。用于图查询，不是语义真相的唯一来源。",
    },
}

_COGNITIVE_PRESENTATION = {
    "MemAgent": {"label": "证据整理", "desc": "负责把对话和用户主动记录整理成可追溯的材料。之所以先停在这里，是为了避免系统把一句话、一次推测或模型总结直接当成事实。"},
    "Reconciler": {"label": "主张校验", "desc": "负责检查一个判断有没有证据支撑、能否被未来事实推翻。这样设计是为了把“我暂时相信什么”和“已经发生了什么”分开，保留被挑战和修正的空间。"},
    "\u8bb0\u5fc6\u68c0\u7d22": {"label": "认知检索", "desc": "负责在需要时找回相关证据、判断和决策背景。它只提供带来源的参考材料，不替你下结论；这样检索结果不会因为“搜到了”就被误认为是真的。"},
    "\u8bb0\u5fc6\u5199\u5165": {"label": "记录证据", "desc": "负责接收用户明确要求保存的内容，并记下来源和时间。它只写入证据，不自动生成结论；这样重要记忆可以留下，未经审查的推断不会混进账本。"},
    "System 2 Writer": {"label": "维护扫描", "desc": "负责找出需要人复查的地方，例如证据不足、缺少反证条件、该复盘的决策、过期承诺和相互矛盾的结果。它只提出问题，不替人修改结论。"},
    "L1_RAW": {"label": "证据", "desc": "保存观察到的原始材料，以及它来自哪里、何时记录、由谁写入。它不评价对错；先保留可追溯的事实基础，之后任何判断才有机会回到原始依据。"},
    "L2_FACT": {"label": "主张", "desc": "保存一个可以被检查的判断，例如“某方案更适合当前目标”。每个主张都要指向证据，并说明什么新情况会推翻它；这样系统不会把结论伪装成永远正确的记忆。"},
    "L3_SUMMARY": {"label": "待审提案", "desc": "保存维护扫描给出的建议，例如该复盘哪个决策、该挑战哪个主张。提案与正式结论分开，是为了让模型可以帮你发现问题，但不能替你做决定。"},
    "L4_IDENTITY": {"label": "决策", "desc": "保存一个真正需要负责的选择：问题是什么、有哪些备选项、最终选了什么、押注什么，以及何时复盘。这样后来能回答“当时为什么这样选，以及现实是否证明它错了”。"},
    "L5_KNOWLEDGE": {"label": "模型", "desc": "保存可复用的因果解释，例如“在什么条件下，什么机制会导致什么结果”。它要求写清适用范围和失效条件，避免把零散经验或泛泛关联包装成规律。"},
    "L6_SCHEMA": {"label": "模型修订", "desc": "保存模型如何被新证据削弱、更新或退休。保留旧版本不是为了堆历史，而是为了复盘：究竟是哪条现实反馈改变了原来的判断。"},
    "L7_INTENTION": {"label": "行动承诺", "desc": "保存由某个决策产生的下一步行动、触发条件和有效期。它不是泛化的提醒清单；把行动绑定到决策，才能知道这件事到底服务于什么目标。"},
    "System 1 Writer": {"label": "回合缓冲", "desc": "负责暂存对话中可能值得保留的材料。它不直接生产结论，避免聊天记录一多就被自动总结、自动升级，最后失去证据边界。"},
    "Vector DB": {"label": "向量索引库", "desc": "位置：C:/Users/CYF/projects/cognitive-os/data/cognitive.vectors.db。它的作用是让系统按语义更快找回证据和主张；它只是检索索引，不能决定什么才是真的。"},
    "Graph DB": {"label": "认知账本", "desc": "位置：C:/Users/CYF/projects/cognitive-os/data/cognitive.db。这里保存证据、主张、模型、决策、行动和结果，以及它们的审计记录；它是系统判断的可追溯依据。"},
    "SQLite Session": {"label": "关系投影", "desc": "位置：C:/Users/CYF/projects/cognitive-os/data/cognitive.kuzu。它把账本中的关系投影成适合查询的图，方便追踪“证据如何影响决策”；即使重建也不会丢失账本事实。"},
}

_COGNITIVE_EXAMPLES = {
    "MemAgent": "例子：你说“下周要决定是否发布新版本”，这里先保留为材料，尚不等于一个正式决定。",
    "Reconciler": "例子：如果主张是“用户会愿意付费”，就要写清“若十位目标用户都拒绝试用，便应重新审查”。",
    "\u8bb0\u5fc6\u68c0\u7d22": "例子：你问“上次为什么没有发布”，系统会找回当时的证据和决策，而不是只给一段无来源的摘要。",
    "\u8bb0\u5fc6\u5199\u5165": "例子：你明确记录“客户 A 在访谈中说价格过高”，它会成为一条带来源的证据。",
    "System 2 Writer": "例子：某决策的复盘日期到了，它会提示你回看，而不会擅自宣布这个决策成功或失败。",
    "L1_RAW": "例子：一份访谈记录、一次数据观测，或用户主动写下的一条事实，都可以是证据。",
    "L2_FACT": "例子：证据显示三位客户都在意价格后，你可以提出“当前定价可能阻碍转化”这条主张。",
    "L3_SUMMARY": "例子：系统发现某主张连续三个月没有新证据，会提出“是否仍然有效”的待审问题。",
    "L4_IDENTITY": "例子：面对“要不要发布”，你记录两个选项、选了哪个、赌的是什么，以及下周何时复盘。",
    "L5_KNOWLEDGE": "例子：你总结“早期产品在价值未被理解前先降价，通常不会解决转化问题”，并写清何时不适用。",
    "L6_SCHEMA": "例子：新数据说明价格并非主要问题时，你不删除旧模型，而是记录它被什么证据削弱。",
    "L7_INTENTION": "例子：决策是“先验证价值”，对应行动承诺可以是“本周完成五次目标用户访谈”。",
    "System 1 Writer": "例子：一次长对话先被缓冲成材料；只有你明确保存或后续审查，才进入正式认知记录。",
    "Vector DB": "例子：你问“定价为什么有风险”，它帮助快速找回相关内容，但不会自行判断哪条内容正确。",
    "Graph DB": "例子：你可以从一个决策一路看到它依赖的主张、主张依据的证据，以及之后得到的结果。",
    "SQLite Session": "例子：审查“某条坏结果推翻了哪些判断”时，关系投影能更快地走这条链。",
}

_COGNITIVE_CHAIN_EXAMPLES = {
    "MemAgent": "你先记录：腾讯约 430 港元时，量价确认与资金流向同时转强。这里先只保留材料，不急着下结论。",
    "Reconciler": "准备写“现在可以买入腾讯”前，先问：这两类信号是否独立、若信号消失该不该推翻这条判断。",
    "\u8bb0\u5fc6\u68c0\u7d22": "之后你问“当时为什么考虑买腾讯”，它找回的应是这两类信号、当时的判断和决策，而不是一句“看好腾讯”。",
    "\u8bb0\u5fc6\u5199\u5165": "你主动保存“430 附近量价与资金流同时确认”，它会先写成有来源的证据，而不是直接写成买入建议。",
    "System 2 Writer": "到了复盘日，它提示检查：430 时未执行、后来价格变化后，当初的判断应被支持、削弱，还是保持不变。",
    "L1_RAW": "证据是：430 附近出现连续放量，且资金流向转强；它只描述观察到的情况，不宣称一定会上涨。",
    "L2_FACT": "基于两条证据提出主张：量价确认和资金流向同时出现时，买入的错误概率更低；若其中一项消失，就应挑战该主张。",
    "L3_SUMMARY": "维护扫描形成待审问题：430 时信号出现却未执行，后续价格变化是否说明“确认后应执行”的规则需要调整？",
    "L4_IDENTITY": "决策写清：在 430 附近、两个信号都确认时是否买入；选项是什么、最终是否执行、赌的是哪种优势、何时复盘。",
    "L5_KNOWLEDGE": "模型解释：右侧交易愿意等确认，付出一点更高成本，换取更少的错误下注；它不保证上涨，只规定何时值得参与。",
    "L6_SCHEMA": "若复盘发现信号确认后仍频繁失败，就修订这个右侧交易模型，并注明是哪些结果让它失效，而不是悄悄改掉规则。",
    "L7_INTENTION": "行动承诺是：只有情绪允许且量价、资金信号仍确认时，才重新评估是否补入；否则保持不动。",
    "System 1 Writer": "这轮关于腾讯的讨论先进入缓冲区；它不会因为聊得很长，就自动把“买入腾讯”写成正式判断。",
    "Vector DB": "当你下次问“腾讯当时的买入条件是什么”，它帮助快速找回 430 附近的证据和判断。",
    "Graph DB": "从这项决策可以一路看到：430 附近的证据 → 买入条件主张 → 右侧交易模型 → 是否执行 → 后续结果。",
    "SQLite Session": "复盘“后续结果影响了哪条买入规则”时，它帮你沿着上面这条关系链快速追溯。",
}


@router.get("/api/architecture")
@cached(ttl=60)
def api_architecture():
    """Serve the architecture graph data (nodes+connections with positions)."""
    p = _HERE / "dashboard" / "dist" / "architecture.json"
    if not p.exists():
        return {"NODES": {}, "CONNECTIONS": []}
    graph = json.loads(p.read_text(encoding="utf-8"))
    overrides = dict(_COGNITIVE_NODE_OVERRIDES)
    overrides.update(_COGNITIVE_STORAGE_OVERRIDES)
    for key, override in overrides.items():
        if key in graph["NODES"]:
            node_override = dict(override)
            if key in _COGNITIVE_SOURCE_LOCATIONS:
                node_override["file"], node_override["loc"] = _COGNITIVE_SOURCE_LOCATIONS[key]
            node_override.update(_COGNITIVE_PRESENTATION.get(key, {}))
            example = _COGNITIVE_CHAIN_EXAMPLES.get(key) or _COGNITIVE_EXAMPLES.get(key)
            if example:
                node_override["desc"] = node_override.get("desc", "") + "\n\n贯穿示例：" + example
            graph["NODES"][key].update(node_override)
    return graph


# ── register ──────────────────────────────────────────────────────────────

print(f"[evolution-hub] COGNITIVE_OS_DB={_COGNITIVE_OS_DB} exists={_COGNITIVE_OS_DB.exists()}")


def register(app):
    app.include_router(router, prefix="/api/plugins/hermes-evolution-hub")
