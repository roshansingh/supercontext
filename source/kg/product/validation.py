from __future__ import annotations

from source.kg.core.models import JsonObject


def require_string_list(payload: JsonObject, key: str, context: str) -> None:
    if key not in payload:
        raise RuntimeError(f"{context} field {key!r} is required")
    values = payload[key]
    if not isinstance(values, list):
        raise RuntimeError(f"{context} field {key!r} must be a list of strings")
    invalid_indexes = [index for index, value in enumerate(values) if not isinstance(value, str)]
    if invalid_indexes:
        raise RuntimeError(f"{context} field {key!r} contains non-string items at indexes {invalid_indexes}")


def require_failure_sentinel_consistency(
    values: list[str],
    score: str,
    score_key: str,
    field_key: str,
) -> None:
    if "none" in values and len(values) > 1:
        raise RuntimeError(f"{field_key} cannot combine 'none' with failure values")
    if score == "Pass" and values != ["none"]:
        raise RuntimeError(f"{score_key}='Pass' requires {field_key} to be ['none']")
    if score != "Pass" and values == ["none"]:
        raise RuntimeError(f"{score_key}={score!r} cannot use {field_key} ['none']")


def require_unique_strings(values: tuple[str, ...], context: str) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{context} contains duplicate value {value!r}")
        seen.add(value)


def normalize_unique_strings(values: tuple[str, ...], context: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    empty_indexes = [index for index, value in enumerate(normalized) if not value]
    if empty_indexes:
        raise ValueError(f"{context} contains empty values at indexes {empty_indexes}")
    require_unique_strings(normalized, context)
    return normalized
