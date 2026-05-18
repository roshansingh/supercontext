from __future__ import annotations

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
            "dotnet parser bridge requires tree-sitter and tree-sitter-c-sharp; "
            "install the optional dotnet extra with `pip install -e '.[dotnet]'` "
            "for local development or `pip install 'bettercontext[dotnet]'` for packaged installs"
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

    file_scoped_namespace = _file_scoped_namespace(root, source)
    _collect(
        root,
        source,
        imports,
        symbols,
        calls,
        qualname_prefix=file_scoped_namespace,
        symbol_key_prefix=file_scoped_namespace,
    )
    has_module_calls = False
    module_symbol = f"{file_scoped_namespace}.<module>" if file_scoped_namespace else "<module>"
    for call in calls:
        if call.get("caller") in {"", file_scoped_namespace}:
            call["caller"] = module_symbol
            call["caller_key"] = module_symbol
            has_module_calls = True
    if has_module_calls:
        symbols.insert(
            0,
            {
                "name": module_symbol,
                "kind": "module",
                "key": module_symbol,
                "line": 1,
                "end_line": root.end_point[0] + 1,
            },
        )
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
    symbol_key_prefix: str,
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

    if node_type in {"namespace_declaration", "file_scoped_namespace_declaration"}:
        name = _namespace_name(node, source)
        if name and node_type == "namespace_declaration":
            namespace_prefix = f"{qualname_prefix}.{name}" if qualname_prefix else name
            namespace_key_prefix = f"{symbol_key_prefix}.{name}" if symbol_key_prefix else name
        else:
            namespace_prefix = qualname_prefix
            namespace_key_prefix = symbol_key_prefix
        for child in node.children:
            _collect(child, source, imports, symbols, calls, namespace_prefix, namespace_key_prefix)
        return

    if node_type in {"class_declaration", "struct_declaration", "interface_declaration", "record_declaration"}:
        name = _declared_name(node, source)
        if name:
            qualname = f"{qualname_prefix}.{name}" if qualname_prefix else name
            symbol_key = f"{symbol_key_prefix}.{name}" if symbol_key_prefix else name
            symbols.append(
                {
                    "name": qualname,
                    "kind": node_type.replace("_declaration", ""),
                    "key": symbol_key,
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
            for child in node.children:
                _collect(child, source, imports, symbols, calls, qualname, symbol_key)
            return

    if node_type in {"method_declaration", "constructor_declaration", "property_declaration"}:
        name = _declared_name(node, source)
        if name:
            qualname = f"{qualname_prefix}.{name}" if qualname_prefix else name
            signature = _signature(node, name)
            symbol_key = f"{symbol_key_prefix}.{signature}" if symbol_key_prefix else signature
            symbols.append(
                {
                    "name": qualname,
                    "kind": node_type.replace("_declaration", ""),
                    "key": symbol_key,
                    "signature": signature,
                    "arity": _parameter_count(node),
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
            for child in node.children:
                _collect(child, source, imports, symbols, calls, qualname, symbol_key)
            return

    if node_type == "invocation_expression":
        callee = _invocation_name(node, source)
        if callee:
            calls.append(
                {
                    "caller": qualname_prefix,
                    "caller_key": symbol_key_prefix,
                    "name": callee,
                    "arity": _argument_count(node),
                    "line": node.start_point[0] + 1,
                }
            )

    for child in node.children:
        _collect(child, source, imports, symbols, calls, qualname_prefix, symbol_key_prefix)


def _using_target(node: Any, source: bytes) -> str:
    found_equals = False
    result = ""
    for child in node.children:
        if child.type in {"=", "name_equals"}:
            found_equals = True
        elif child.type in {"qualified_name", "identifier"}:
            result = _node_text(child, source)
            if found_equals:
                return result
    return result


def _file_scoped_namespace(root: Any, source: bytes) -> str:
    for child in root.children:
        if child.type == "file_scoped_namespace_declaration":
            return _namespace_name(child, source)
    return ""


def _namespace_name(node: Any, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return _node_text(name, source)
    for child in node.children:
        if child.type in {"qualified_name", "identifier"}:
            return _node_text(child, source)
    return ""


def _declared_name(node: Any, source: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return _node_text(name, source)
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source)
    return ""


def _invocation_name(node: Any, source: bytes) -> str:
    function = node.child_by_field_name("function")
    if function is not None:
        return _node_text(function, source)
    for child in node.children:
        if child.type in {"identifier", "member_access_expression", "generic_name", "qualified_name"}:
            return _node_text(child, source)
    return ""


def _signature(node: Any, name: str) -> str:
    if node.type in {"method_declaration", "constructor_declaration"}:
        return f"{name}/{_parameter_count(node)}"
    return name


def _parameter_count(node: Any) -> int:
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        return 0
    return sum(1 for child in parameters.children if child.type == "parameter")


def _argument_count(node: Any) -> int:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return 0
    return sum(1 for child in arguments.children if child.type == "argument")


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
