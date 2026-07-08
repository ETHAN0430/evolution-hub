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
