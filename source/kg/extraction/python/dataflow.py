from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from source.kg.core.models import Coverage, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.normalization.python.imports import NormalizedImport


TENANT_ID = "local-dev"


@dataclass(frozen=True)
class LiteralRef:
    module_name: str
    name: str


@dataclass(frozen=True)
class ResolvedValue:
    value: object
    source: str
    expression: str


@dataclass(frozen=True)
class UnresolvedValue:
    reason: str
    expression: str


@dataclass(frozen=True)
class LiteralIndex:
    values: dict[LiteralRef, ast.AST]

    def get(self, module_name: str, name: str) -> ast.AST | None:
        return self.values.get(LiteralRef(module_name, name))


@dataclass(frozen=True)
class ValueScope:
    local_values: dict[str, ast.AST] = field(default_factory=dict)
    imported_modules: dict[str, str] = field(default_factory=dict)
    imported_values: dict[str, LiteralRef] = field(default_factory=dict)
    env_values: dict[str, str] = field(default_factory=dict)


class ValueResolver:
    def __init__(self, scope: ValueScope | None = None, literal_index: LiteralIndex | None = None) -> None:
        self.scope = scope or ValueScope()
        self.literal_index = literal_index or LiteralIndex({})
        self._resolving_names: set[str] = set()
        self._resolving_refs: set[LiteralRef] = set()

    def resolve_value(self, node: ast.AST) -> ResolvedValue | UnresolvedValue:
        if isinstance(node, ast.Constant):
            return ResolvedValue(node.value, "literal", _expression(node))

        if isinstance(node, ast.List):
            return self._resolve_sequence(node.elts, list, _expression(node))

        if isinstance(node, ast.Tuple):
            return self._resolve_sequence(node.elts, tuple, _expression(node))

        if isinstance(node, ast.Set):
            return self._resolve_sequence(node.elts, set, _expression(node))

        if isinstance(node, ast.Dict):
            return self._resolve_dict(node)

        if isinstance(node, ast.Name):
            return self._resolve_name(node)

        if isinstance(node, ast.Attribute):
            return self._resolve_attribute(node)

        if isinstance(node, ast.Call):
            return self._resolve_call(node)

        if isinstance(node, ast.Subscript):
            return self._resolve_subscript(node)

        if isinstance(node, ast.JoinedStr):
            return self._resolve_joined_str(node)

        return UnresolvedValue(f"unsupported_{type(node).__name__}", _expression(node))

    def _resolve_name(self, node: ast.Name) -> ResolvedValue | UnresolvedValue:
        name = node.id
        if name in self._resolving_names:
            return UnresolvedValue("cyclic_name", name)
        if name in self.scope.local_values:
            self._resolving_names.add(name)
            try:
                resolved = self.resolve_value(self.scope.local_values[name])
            finally:
                self._resolving_names.remove(name)
            if isinstance(resolved, ResolvedValue):
                return ResolvedValue(resolved.value, f"local:{name}", _expression(node))
            return resolved
        imported_ref = self.scope.imported_values.get(name)
        if imported_ref is not None:
            return self._resolve_literal_ref(imported_ref, _expression(node))
        return UnresolvedValue("unknown_name", _expression(node))

    def _resolve_attribute(self, node: ast.Attribute) -> ResolvedValue | UnresolvedValue:
        parts = _attribute_parts(node)
        if len(parts) < 2:
            return UnresolvedValue("unsupported_attribute", _expression(node))
        root = parts[0]
        module_name = self.scope.imported_modules.get(root)
        if module_name is None:
            return UnresolvedValue("unknown_attribute_root", _expression(node))
        ref = LiteralRef(".".join([module_name, *parts[1:-1]]), parts[-1])
        return self._resolve_literal_ref(ref, _expression(node))

    def _resolve_call(self, node: ast.Call) -> ResolvedValue | UnresolvedValue:
        call_name = _call_name(node.func)
        env_name = self._env_name_from_call(call_name, node)
        if env_name is None:
            return UnresolvedValue("unsupported_call", _expression(node))
        if env_name not in self.scope.env_values:
            return UnresolvedValue("unknown_env_value", _expression(node))
        return ResolvedValue(self.scope.env_values[env_name], f"env:{env_name}", _expression(node))

    def _resolve_subscript(self, node: ast.Subscript) -> ResolvedValue | UnresolvedValue:
        env_name = self._env_name_from_subscript(node)
        if env_name is not None:
            if env_name not in self.scope.env_values:
                return UnresolvedValue("unknown_env_value", _expression(node))
            return ResolvedValue(self.scope.env_values[env_name], f"env:{env_name}", _expression(node))

        if not isinstance(node.slice, ast.Constant):
            return UnresolvedValue("unsupported_subscript_key", _expression(node))
        resolved_container = self.resolve_value(node.value)
        if not isinstance(resolved_container, ResolvedValue) or not isinstance(resolved_container.value, dict):
            return UnresolvedValue("unsupported_subscript_container", _expression(node))
        key = node.slice.value
        if key not in resolved_container.value:
            return UnresolvedValue("missing_subscript_key", _expression(node))
        return ResolvedValue(resolved_container.value[key], "dict_literal", _expression(node))

    def _resolve_sequence(self, nodes: list[ast.AST], factory: type, expression: str) -> ResolvedValue | UnresolvedValue:
        values = []
        for node in nodes:
            resolved = self.resolve_value(node)
            if not isinstance(resolved, ResolvedValue):
                return resolved
            values.append(resolved.value)
        return ResolvedValue(factory(values), "literal", expression)

    def _resolve_dict(self, node: ast.Dict) -> ResolvedValue | UnresolvedValue:
        values: dict[object, object] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                return UnresolvedValue("unsupported_dict_unpack", _expression(node))
            resolved_key = self.resolve_value(key_node)
            if not isinstance(resolved_key, ResolvedValue):
                return resolved_key
            resolved_value = self.resolve_value(value_node)
            if not isinstance(resolved_value, ResolvedValue):
                return resolved_value
            try:
                values[resolved_key.value] = resolved_value.value
            except TypeError:
                return UnresolvedValue("unhashable_dict_key", _expression(key_node))
        return ResolvedValue(values, "literal", _expression(node))

    def _resolve_joined_str(self, node: ast.JoinedStr) -> ResolvedValue | UnresolvedValue:
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return UnresolvedValue("unsupported_joined_str", _expression(node))
            parts.append(value.value)
        return ResolvedValue("".join(parts), "literal", _expression(node))

    def _resolve_literal_ref(self, ref: LiteralRef, expression: str) -> ResolvedValue | UnresolvedValue:
        if ref in self._resolving_refs:
            return UnresolvedValue("cyclic_literal_ref", expression)
        node = self.literal_index.get(ref.module_name, ref.name)
        if node is None:
            return UnresolvedValue("unknown_literal_ref", expression)
        self._resolving_refs.add(ref)
        try:
            resolved = self.resolve_value(node)
        finally:
            self._resolving_refs.remove(ref)
        if isinstance(resolved, ResolvedValue):
            return ResolvedValue(resolved.value, f"literal_ref:{ref.module_name}.{ref.name}", expression)
        return resolved

    def _env_name_from_call(self, call_name: str, node: ast.Call) -> str | None:
        if call_name not in {"os.getenv", "os.environ.get"}:
            return None
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            return None
        return node.args[0].value

    def _env_name_from_subscript(self, node: ast.Subscript) -> str | None:
        if _call_name(node.value) != "os.environ":
            return None
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
            return None
        return node.slice.value


def build_repo_literal_index(repo: RepoSnapshot) -> LiteralIndex:
    values: dict[LiteralRef, ast.AST] = {}
    for file_path in repo.python_files:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue
        module_name = module_name_for_path(repo, file_path)
        for name, value in module_literal_assignments(tree).items():
            values[LiteralRef(module_name, name)] = value
    return LiteralIndex(values)


def module_literal_assignments(tree: ast.AST) -> dict[str, ast.AST]:
    if not isinstance(tree, ast.Module):
        return {}
    assignments: dict[str, ast.AST] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and _is_supported_literal_expression(statement.value):
                    assignments[target.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
            and _is_supported_literal_expression(statement.value)
        ):
            assignments[statement.target.id] = statement.value
    return assignments


def local_literal_assignments(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for statement in function_node.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and _is_supported_local_expression(statement.value):
                    assignments[target.id] = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
            and _is_supported_local_expression(statement.value)
        ):
            assignments[statement.target.id] = statement.value
    return assignments


def bind_args(call_node: ast.Call, function_def: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST]:
    positional_params = [*function_def.args.posonlyargs, *function_def.args.args]
    keyword_params = {param.arg for param in [*positional_params, *function_def.args.kwonlyargs]}
    bindings: dict[str, ast.AST] = {}
    for index, arg_node in enumerate(call_node.args):
        if index >= len(positional_params):
            break
        bindings[positional_params[index].arg] = arg_node
    for keyword in call_node.keywords:
        if keyword.arg is not None and keyword.arg in keyword_params:
            bindings[keyword.arg] = keyword.value
    return bindings


def body_call_nodes(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    collector = _CallCollector()
    for statement in function_node.body:
        collector.visit(statement)
    return collector.calls


def import_bindings(imports: list[NormalizedImport]) -> tuple[dict[str, str], dict[str, LiteralRef]]:
    imported_modules: dict[str, str] = {}
    imported_values: dict[str, LiteralRef] = {}
    for import_ref in imports:
        if import_ref.module_name is None:
            continue
        if import_ref.imported_names:
            for imported_name in import_ref.imported_names:
                imported_values[imported_name] = LiteralRef(import_ref.module_name, imported_name)
            continue
        if import_ref.alias:
            imported_modules[import_ref.alias] = import_ref.module_name
        else:
            imported_modules[import_ref.import_root] = import_ref.import_root
    return imported_modules, imported_values


def unresolved_coverage(
    repo: RepoSnapshot,
    file_path: Path,
    unresolved: UnresolvedValue,
    source_system: str,
    *,
    predicate: str,
    line: int,
) -> Coverage:
    return Coverage(
        tenant_id=TENANT_ID,
        predicate=predicate,
        scope_ref={
            "repo": repo.name,
            "language": "python",
            "path": str(file_path.relative_to(repo.root)),
            "line": line,
            "expression": unresolved.expression,
            "reason": unresolved.reason,
        },
        state="uninstrumented",
        source_system=source_system,
    )


def module_name_for_path(repo: RepoSnapshot, file_path: Path) -> str:
    relative = file_path.relative_to(repo.root).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts) or repo.name


def resolved_to_json(value: ResolvedValue) -> JsonObject:
    return {"value": _json_safe(value.value), "source": value.source, "expression": value.expression}


def _is_supported_literal_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_supported_literal_expression(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_supported_literal_expression(key) and _is_supported_literal_expression(value)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.JoinedStr):
        return all(isinstance(value, ast.Constant) and isinstance(value.value, str) for value in node.values)
    return False


def _is_supported_local_expression(node: ast.AST) -> bool:
    return _is_supported_literal_expression(node) or isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript))


def _attribute_parts(node: ast.Attribute) -> list[str]:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = _attribute_parts(node)
        return ".".join(parts)
    return ""


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    return str(value)


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
