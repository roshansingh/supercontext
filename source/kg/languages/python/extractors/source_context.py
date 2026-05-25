from __future__ import annotations

import ast


SOURCE_CONTEXT_MAX_CHARS = 240


def source_line(source_text: str | None, line: int) -> str | None:
    if source_text is None or line < 1:
        return None
    lines = source_text.splitlines()
    if line > len(lines):
        return None
    return trim_source_context(lines[line - 1].strip())


def source_excerpt(source_text: str | None, node: ast.AST) -> str | None:
    if source_text is None:
        return None
    try:
        segment = ast.get_source_segment(source_text, node)
    except Exception:
        return None
    if not segment:
        return None
    return trim_source_context(" ".join(segment.strip().split()))


def trim_source_context(value: str) -> str | None:
    if not value:
        return None
    if len(value) <= SOURCE_CONTEXT_MAX_CHARS:
        return value
    return f"{value[: SOURCE_CONTEXT_MAX_CHARS - 3]}..."
