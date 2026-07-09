"""Canonical Memory-to-Memory relation types used by HY Memory."""

RELATED_TO = "RELATED_TO"
CORRECTED = "CORRECTED"
SHAPED_BY = "SHAPED_BY"
BUILDS_ON = "BUILDS_ON"
SUPPORTED_BY = "SUPPORTED_BY"
CONTRADICTED_BY = "CONTRADICTED_BY"
LED_TO = "LED_TO"
RESULTED_IN = "RESULTED_IN"

COGNITIVE_EDGE_TYPES = frozenset({
    CORRECTED,
    SHAPED_BY,
    BUILDS_ON,
    SUPPORTED_BY,
    CONTRADICTED_BY,
    LED_TO,
    RESULTED_IN,
})
MEMORY_EDGE_TYPES = frozenset({RELATED_TO, *COGNITIVE_EDGE_TYPES})


def normalize_memory_edge_type(edge_type: str) -> str:
    """Return a validated uppercase relation type, or RELATED_TO as fallback."""
    normalized = (edge_type or RELATED_TO).upper()
    return normalized if normalized in MEMORY_EDGE_TYPES else RELATED_TO


def infer_cognitive_edge_type_from_reason(reason: str) -> str:
    """Infer an obvious cognitive relation type from free-form reason text."""
    text = (reason or "").lower()
    keyword_map = [
        (CONTRADICTED_BY, (
            "反驳", "矛盾", "冲突", "否定", "推翻", "不再成立",
            "contradict", "contradicted", "conflict", "refute", "falsify",
        )),
        (CORRECTED, (
            "修正", "纠正", "补充", "精炼", "迭代", "新版", "旧版",
            "correct", "corrected", "refine", "refined", "supersede", "update",
        )),
        (RESULTED_IN, (
            "产生结果", "结果是", "带来结果", "导致结果", "产出", "落地为",
            "resulted in", "produced", "led to the outcome", "outcome",
        )),
        (LED_TO, (
            "导致", "引发", "促成", "推导出", "得出", "形成", "演化成", "带来",
            "led to", "leads to", "caused", "derived", "inferred",
        )),
        (SHAPED_BY, (
            "塑造", "受影响", "被影响", "源自经历", "由经历", "生活经历",
            "shaped by", "influenced by", "formed by", "rooted in experience",
        )),
        (BUILDS_ON, (
            "建立在", "基于", "依赖", "承接", "上层", "基础框架",
            "builds on", "built on", "based on", "depends on", "foundation",
        )),
        (SUPPORTED_BY, (
            "支持", "支撑", "证据", "佐证", "证明", "印证",
            "supported by", "evidence", "backed by", "validated by",
        )),
    ]
    for edge_type, keywords in keyword_map:
        if any(keyword in text for keyword in keywords):
            return edge_type
    return RELATED_TO


def plan_legacy_related_direction(
    edge_type: str,
    a_id: str,
    a_time,
    b_id: str,
    b_time,
) -> dict:
    """Choose a conservative direction for a migrated bidirectional RELATED_TO pair."""
    if edge_type not in COGNITIVE_EDGE_TYPES:
        return {"status": "skip", "reason": "not_cognitive"}
    if not a_time or not b_time or a_time == b_time:
        return {"status": "ambiguous", "reason": "missing_or_equal_time"}

    older, newer = (a_id, b_id) if a_time < b_time else (b_id, a_id)
    if edge_type in {LED_TO, RESULTED_IN, CONTRADICTED_BY}:
        return {"status": "migrate", "source": older, "target": newer}
    if edge_type in {CORRECTED, SHAPED_BY, BUILDS_ON}:
        return {"status": "migrate", "source": newer, "target": older}
    return {"status": "ambiguous", "reason": "direction_requires_content_audit"}


def cosine_similarity(a, b) -> float:
    """Small dependency-free cosine helper for graph maintenance tasks."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for left, right in zip(a, b):
        dot += float(left) * float(right)
        norm_a += float(left) * float(left)
        norm_b += float(right) * float(right)
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))
