from __future__ import annotations

from pathlib import Path
from typing import Any

from source.kg.core.models import JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import ExtractionContext


def parse_dotnet_repo(repo: RepoSnapshot, ctx: ExtractionContext | None = None) -> dict[str, JsonObject]:
    cache_key = f"{repo.root}:{repo.commit_sha}"
    if ctx is not None:
        cached = ctx.parsed_by_language.setdefault("dotnet", {}).get(cache_key)
        if isinstance(cached, dict):
            return cached

    parsed = _parse_dotnet_repo_uncached(repo)
    if ctx is not None:
        ctx.parsed_by_language.setdefault("dotnet", {})[cache_key] = parsed
    return parsed


def _parse_dotnet_repo_uncached(repo: RepoSnapshot) -> dict[str, JsonObject]:
    try:
        import tree_sitter
        import tree_sitter_c_sharp as tscs
    except ImportError as exc:
        raise RuntimeError(
            "dotnet parser bridge requires tree-sitter and tree-sitter-c-sharp"
        ) from exc

    language = tree_sitter.Language(tscs.language())
    parser = tree_sitter.Parser(language)

    result: dict[str, JsonObject] = {}
    for file_path in repo.files_by_language.get("dotnet", ()):
        if file_path.suffix != ".cs":
            continue
        relative = str(file_path.relative_to(repo.root))
        try:
            source = file_path.read_bytes()
            tree = parser.parse(source)
        except (OSError, ValueError) as exc:
            result[relative] = {
                "imports": [],
                "symbols": [],
                "calls": [],
                "parse_diagnostics": [{"line": 1, "message": f"parse failed: {exc}"}],
            }
            continue

        result[relative] = _walk_tree(tree.root_node, source)
    return result


def _walk_tree(root: Any, source: bytes) -> JsonObject:
    imports: list[JsonObject] = []
    symbols: list[JsonObject] = []
    calls: list[JsonObject] = []
    diagnostics: list[JsonObject] = []

    if root.has_error:
        diagnostics.append({"line": root.start_point[0] + 1, "message": "tree-sitter reported parse errors"})

    _collect(root, source, imports, symbols, calls, qualname_prefix="")
    return {
        "imports": imports,
        "symbols": symbols,
        "calls": calls,
        "parse_diagnostics": diagnostics,
    }


def _collect(
    node: Any,
    source: bytes,
    imports: list[JsonObject],
    symbols: list[JsonObject],
    calls: list[JsonObject],
    qualname_prefix: str,
) -> None:
    node_type = node.type
    if node_type == "using_directive":
        target = _using_target(node, source)
        if target:
            imports.append(
                {
                    "raw_target": target,
                    "line": node.start_point[0] + 1,
                    "imported_names": [],
                    "local_names": [],
                }
            )
        return

    if node_type in {"class_declaration", "struct_declaration", "interface_declaration", "record_declaration"}:
        name = _declared_name(node, source)
        if name:
            qualname = f"{qualname_prefix}.{name}" if qualname_prefix else name
            symbols.append(
                {
                    "name": qualname,
                    "kind": node_type.replace("_declaration", ""),
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
            for child in node.children:
                _collect(child, source, imports, symbols, calls, qualname_prefix=qualname)
            return

    if node_type in {"method_declaration", "constructor_declaration", "property_declaration"}:
        name = _declared_name(node, source)
        if name:
            qualname = f"{qualname_prefix}.{name}" if qualname_prefix else name
            symbols.append(
                {
                    "name": qualname,
                    "kind": node_type.replace("_declaration", ""),
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
            for child in node.children:
                _collect(child, source, imports, symbols, calls, qualname_prefix=qualname)
            return

    if node_type == "invocation_expression":
        callee = _invocation_name(node, source)
        if callee:
            calls.append(
                {
                    "caller": qualname_prefix,
                    "name": callee,
                    "line": node.start_point[0] + 1,
                }
            )

    for child in node.children:
        _collect(child, source, imports, symbols, calls, qualname_prefix)


def _using_target(node: Any, source: bytes) -> str:
    found_equals = False
    result = ""
    for child in node.children:
        if child.type == "=":
            found_equals = True
        elif child.type in {"qualified_name", "identifier"}:
            result = _node_text(child, source)
            if found_equals:
                return result
    return result


def _declared_name(node: Any, source: bytes) -> str:
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source)
    return ""


def _invocation_name(node: Any, source: bytes) -> str:
    for child in node.children:
        if child.type in {"identifier", "member_access_expression", "generic_name", "qualified_name"}:
            return _node_text(child, source)
    return ""


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
