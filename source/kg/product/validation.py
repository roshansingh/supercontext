from __future__ import annotations

from source.kg.core.models import JsonObject


def require_string_list(payload: JsonObject, key: str, context: str) -> None:
    values = payload.get(key, [])
    if not isinstance(values, list):
        raise RuntimeError(f"{context} field {key!r} must be a list of strings")
    invalid_indexes = [index for index, value in enumerate(values) if not isinstance(value, str)]
    if invalid_indexes:
        raise RuntimeError(f"{context} field {key!r} contains non-string items at indexes {invalid_indexes}")
