from __future__ import annotations

import json
from collections.abc import Iterator

from source.kg.core.models import JsonObject


def parse_json_object_result(result_text: str, context: str) -> JsonObject:
    for candidate in _candidate_json_texts(result_text):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    decoder = json.JSONDecoder()
    for start, char in enumerate(result_text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(result_text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise RuntimeError(f"Claude returned non-JSON {context} output: {result_text[:500]}")


def _candidate_json_texts(result_text: str) -> Iterator[str]:
    stripped = result_text.strip()
    if stripped:
        yield stripped

    fence_parts = stripped.split("```")
    for index in range(1, len(fence_parts), 2):
        block = fence_parts[index].strip()
        if block.startswith("json"):
            block = block[4:].strip()
        if block:
            yield block
