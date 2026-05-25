from __future__ import annotations

from source.kg.core.models import JsonObject


def call_site_from_qualifier(qualifier: object) -> JsonObject | None:
    if not isinstance(qualifier, dict):
        return None
    source_line = qualifier.get("source_line")
    source_excerpt = qualifier.get("source_excerpt")
    if not isinstance(source_line, str) and not isinstance(source_excerpt, str):
        return None
    row: JsonObject = {}
    if isinstance(source_line, str) and source_line.strip():
        row["source_line"] = source_line
    if isinstance(source_excerpt, str) and source_excerpt.strip():
        row["source_excerpt"] = source_excerpt
    return row or None
