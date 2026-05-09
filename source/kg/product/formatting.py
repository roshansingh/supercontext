from __future__ import annotations

from typing import Any

from source.kg.core.models import JsonObject


def compact_evidence_item(row: JsonObject) -> JsonObject:
    return {
        "claim": row.get("claim"),
        "fact_type": row.get("fact_type"),
        "subject": row.get("subject"),
        "object": row.get("object"),
        "repo": row.get("repo"),
        "path": row.get("path"),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
        "source_system": row.get("source_system"),
        "derivation_class": row.get("derivation_class"),
        "confidence": row.get("confidence"),
        "reconciliation_group": row.get("reconciliation_group"),
        "possible_match": row.get("possible_match"),
        "similarity": row.get("similarity"),
        "step": row.get("step"),
        "qualifier": row.get("qualifier", {}),
    }


def bullet_lines(values: list[Any]) -> list[str]:
    if not values:
        return ["- None."]
    return [f"- {str(value).strip()}" for value in values]


def one_line(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
