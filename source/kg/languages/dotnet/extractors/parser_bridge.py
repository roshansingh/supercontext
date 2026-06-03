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
            "for local development or `pip install 'supercontext[dotnet]'` for packaged installs"
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
    bindings: list[JsonObject] = []
    local_assignments: list[JsonObject] = []
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
        bindings,
        local_assignments,
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
        "bindings": bindings,
        "local_assignments": local_assignments,
        "parse_diagnostics": diagnostics,
    }


def _collect(
    node: Any,
    source: bytes,
    imports: list[JsonObject],
    symbols: list[JsonObject],
    calls: list[JsonObject],
    bindings: list[JsonObject],
    local_assignments: list[JsonObject],
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
            _collect(child, source, imports, symbols, calls, bindings, local_assignments, namespace_prefix, namespace_key_prefix)
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
                    "bases": _base_types(node, source),
                    "line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                }
            )
            # Primary-constructor parameters are class-scoped receiver bindings.
            for binding in _parameter_bindings(node, source, qualname):
                bindings.append(binding)
            for child in node.children:
                _collect(child, source, imports, symbols, calls, bindings, local_assignments, qualname, symbol_key)
            return

    if node_type == "field_declaration":
        for binding in _field_bindings(node, source, qualname_prefix):
            bindings.append(binding)
        # fall through: keep descending so calls inside field initializers are still collected

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
            for binding in _parameter_bindings(node, source, qualname):
                bindings.append(binding)
            for child in node.children:
                _collect(child, source, imports, symbols, calls, bindings, local_assignments, qualname, symbol_key)
            return

    if node_type == "local_declaration_statement":
        for assignment in _local_assignments(node, source, qualname_prefix):
            local_assignments.append(assignment)

    if node_type == "invocation_expression":
        callee = _invocation_name(node, source)
        if callee:
            calls.append(
                {
                    "caller": qualname_prefix,
                    "caller_key": symbol_key_prefix,
                    "name": callee,
                    "method": _invocation_method(node, source),
                    "type_args": _invocation_type_args(node, source),
                    "receiver": _invocation_receiver(node, source),
                    "first_arg": _invocation_first_arg(node, source),
                    "arity": _argument_count(node),
                    "line": node.start_point[0] + 1,
                }
            )

    for child in node.children:
        _collect(child, source, imports, symbols, calls, bindings, local_assignments, qualname_prefix, symbol_key_prefix)


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


def _base_types(node: Any, source: bytes) -> list[JsonObject]:
    base_list = next((child for child in node.children if child.type == "base_list"), None)
    if base_list is None:
        return []
    return [
        _type_ref(child, source)
        for child in base_list.children
        if child.type in {"identifier", "generic_name", "qualified_name"}
    ]


def _type_ref(node: Any, source: bytes) -> JsonObject:
    if node.type == "generic_name":
        identifier = next((child for child in node.children if child.type == "identifier"), None)
        name = _node_text(identifier, source) if identifier is not None else _node_text(node, source)
        return {"name": name, "type_args": _type_args(node, source)}
    return {"name": _node_text(node, source), "type_args": []}


def _type_args(generic_name: Any, source: bytes) -> list[str]:
    argument_list = next((child for child in generic_name.children if child.type == "type_argument_list"), None)
    if argument_list is None:
        return []
    return [
        _node_text(child, source)
        for child in argument_list.children
        if child.type not in {"<", ">", ","}
    ]


def _generic_name_in(function: Any) -> Any | None:
    if function.type == "generic_name":
        return function
    if function.type == "member_access_expression":
        name = function.child_by_field_name("name")
        if name is not None and name.type == "generic_name":
            return name
    return None


def _invocation_type_args(node: Any, source: bytes) -> list[str]:
    function = node.child_by_field_name("function")
    if function is None:
        return []
    generic_name = _generic_name_in(function)
    return _type_args(generic_name, source) if generic_name is not None else []


def _parameter_bindings(node: Any, source: bytes, scope: str) -> list[JsonObject]:
    parameter_list = next((child for child in node.children if child.type == "parameter_list"), None)
    if parameter_list is None:
        return []
    bindings: list[JsonObject] = []
    for child in parameter_list.children:
        if child.type != "parameter":
            continue
        type_node = child.child_by_field_name("type")
        name_node = child.child_by_field_name("name")
        if type_node is None or name_node is None:
            continue
        bindings.append(
            {
                "scope": scope,
                "name": _node_text(name_node, source),
                "type": _type_ref(type_node, source)["name"],
                "line": child.start_point[0] + 1,
            }
        )
    return bindings


def _field_bindings(node: Any, source: bytes, scope: str) -> list[JsonObject]:
    declaration = next((child for child in node.children if child.type == "variable_declaration"), None)
    if declaration is None:
        return []
    type_node = declaration.child_by_field_name("type")
    if type_node is None:
        return []
    type_name = _type_ref(type_node, source)["name"]
    bindings: list[JsonObject] = []
    for child in declaration.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is None:
            continue
        bindings.append(
            {
                "scope": scope,
                "name": _node_text(name_node, source),
                "type": type_name,
                "line": child.start_point[0] + 1,
            }
        )
    return bindings


def _local_assignments(node: Any, source: bytes, scope: str) -> list[JsonObject]:
    declaration = next((child for child in node.children if child.type == "variable_declaration"), None)
    if declaration is None:
        return []
    assignments: list[JsonObject] = []
    for child in declaration.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is None:
            continue
        resolved = _initializer_type(child, source)
        if resolved is None:
            continue
        assignments.append(
            {
                "scope": scope,
                "name": _node_text(name_node, source),
                "type": resolved,
                "line": child.start_point[0] + 1,
            }
        )
    return assignments


def _initializer_type(declarator: Any, source: bytes) -> str | None:
    """Resolve the static type produced by a variable initializer, structurally.

    Handles ``new T(...)`` (object creation type) and generic-method initializers such as
    ``x.Adapt<T>()`` / ``Map<T>(...)`` (the generic type argument). Returns None for
    initializers whose type is not statically visible (e.g. ``x.ToDto()``).
    """
    value = declarator.child_by_field_name("value")
    if value is None:
        for child in declarator.children:
            if child.type not in {"=", "identifier"}:
                value = child
                break
    if value is None:
        return None
    if value.type == "object_creation_expression":
        type_node = value.child_by_field_name("type")
        return _type_ref(type_node, source)["name"] if type_node is not None else None
    if value.type == "invocation_expression":
        type_args = _invocation_type_args(value, source)
        return type_args[0] if type_args else None
    return None


def _invocation_receiver(node: Any, source: bytes) -> str:
    function = node.child_by_field_name("function")
    if function is None or function.type != "member_access_expression":
        return ""
    expression = function.child_by_field_name("expression")
    if expression is None:
        return ""
    if expression.type == "identifier":
        return _node_text(expression, source)
    # `this.field.Method(...)` -> the field name is the receiver binding to resolve.
    if expression.type == "member_access_expression":
        inner = expression.child_by_field_name("expression")
        name = expression.child_by_field_name("name")
        if inner is not None and inner.type in {"this_expression", "this"} and name is not None and name.type == "identifier":
            return _node_text(name, source)
    return ""


def _invocation_first_arg(node: Any, source: bytes) -> JsonObject:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return {"kind": "none"}
    argument = next((child for child in arguments.children if child.type == "argument"), None)
    if argument is None:
        return {"kind": "none"}
    expression = next((child for child in argument.children if child.is_named), None)
    if expression is None:
        return {"kind": "none"}
    if expression.type == "object_creation_expression":
        type_node = expression.child_by_field_name("type")
        return {"kind": "object_creation", "type": _type_ref(type_node, source)["name"] if type_node is not None else None}
    if expression.type == "identifier":
        return {"kind": "identifier", "name": _node_text(expression, source)}
    return {"kind": "other"}


def _invocation_method(node: Any, source: bytes) -> str:
    function = node.child_by_field_name("function")
    if function is None:
        return ""
    target = function
    if function.type == "member_access_expression":
        name = function.child_by_field_name("name")
        if name is not None:
            target = name
    if target.type == "generic_name":
        identifier = next((child for child in target.children if child.type == "identifier"), None)
        return _node_text(identifier, source) if identifier is not None else ""
    if target.type == "identifier":
        return _node_text(target, source)
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
