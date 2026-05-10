from __future__ import annotations

import ast
import configparser
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
class ConfigObjectRef:
    module_name: str
    object_name: str
    attribute_path: tuple[str, ...]


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
    config_object_values: dict[ConfigObjectRef, tuple[ast.AST, ...]] = field(default_factory=dict)

    def get(self, module_name: str, name: str) -> ast.AST | None:
        return self.values.get(LiteralRef(module_name, name))

    def find_under_prefixes(self, module_prefixes: tuple[str, ...], name: str) -> list[tuple[LiteralRef, ast.AST]]:
        results = []
        for ref, node in self.values.items():
            if ref.name != name:
                continue
            if any(ref.module_name == prefix or ref.module_name.startswith(f"{prefix}.") for prefix in module_prefixes):
                results.append((ref, node))
        return sorted(results, key=lambda item: (item[0].module_name, item[0].name))

    def get_config_object_values(
        self,
        module_name: str,
        object_name: str,
        attribute_path: tuple[str, ...],
    ) -> tuple[ast.AST, ...]:
        return self.config_object_values.get(ConfigObjectRef(module_name, object_name, attribute_path), ())


@dataclass(frozen=True)
class ConfigChild:
    class_name: str
    arg_roots: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class ConfigClassInfo:
    params: tuple[str, ...]
    local_parser_names: frozenset[str]
    children: dict[str, ConfigChild]
    options_by_root: dict[str, dict[str, str]]


@dataclass(frozen=True)
class ValueScope:
    local_values: dict[str, ast.AST] = field(default_factory=dict)
    imported_modules: dict[str, str] = field(default_factory=dict)
    imported_values: dict[str, LiteralRef] = field(default_factory=dict)
    env_values: dict[str, str] = field(default_factory=dict)
    blocked_names: set[str] = field(default_factory=set)


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
        if name in self.scope.blocked_names:
            return UnresolvedValue("unknown_local_binding", name)
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
            return self._resolve_imported_name(imported_ref, _expression(node))
        return UnresolvedValue("unknown_name", _expression(node))

    def _resolve_attribute(self, node: ast.Attribute) -> ResolvedValue | UnresolvedValue:
        parts = _attribute_parts(node)
        if len(parts) < 2:
            return UnresolvedValue("unsupported_attribute", _expression(node))
        root = parts[0]
        module_name = self.scope.imported_modules.get(root)
        if module_name is not None:
            ref = LiteralRef(".".join([module_name, *parts[1:-1]]), parts[-1])
            return self._resolve_literal_ref(ref, _expression(node))
        imported_ref = self.scope.imported_values.get(root)
        if imported_ref is not None:
            resolved = self._resolve_imported_attribute(imported_ref, parts[1:], _expression(node))
            if resolved is not None:
                return resolved
        return UnresolvedValue("unknown_attribute_root", _expression(node))

    def _resolve_imported_attribute(
        self,
        imported_ref: LiteralRef,
        attribute_parts: list[str],
        expression: str,
    ) -> ResolvedValue | UnresolvedValue | None:
        if not attribute_parts:
            return None
        values = []
        sources = []
        candidates = self.literal_index.find_under_prefixes((f"{imported_ref.module_name}.{imported_ref.name}",), attribute_parts[-1])
        for ref, _ in candidates:
            resolved = self._resolve_literal_ref(ref, expression)
            if not isinstance(resolved, ResolvedValue):
                continue
            values.append(resolved.value)
            sources.append(f"{ref.module_name}.{ref.name}")

        config_values = self.literal_index.get_config_object_values(
            imported_ref.module_name,
            imported_ref.name,
            tuple(attribute_parts),
        )
        for value_node in config_values:
            resolved = self.resolve_value(value_node)
            if not isinstance(resolved, ResolvedValue):
                continue
            values.append(resolved.value)
        if config_values:
            sources.append(
                f"config_object:{imported_ref.module_name}.{imported_ref.name}.{'.'.join(attribute_parts)}"
            )
        unique_values = _unique_values(values)
        if not unique_values:
            return None
        source = "literal_ref:" + ",".join(sources)
        if len(unique_values) == 1:
            return ResolvedValue(unique_values[0], source, expression)
        return ResolvedValue(tuple(unique_values), source, expression)

    def _resolve_imported_name(self, imported_ref: LiteralRef, expression: str) -> ResolvedValue | UnresolvedValue:
        resolved = self._resolve_literal_ref(imported_ref, expression)
        if isinstance(resolved, ResolvedValue) or resolved.reason != "unknown_literal_ref":
            return resolved
        candidates = self.literal_index.find_under_prefixes((imported_ref.module_name,), imported_ref.name)
        if not candidates:
            return resolved
        values = []
        sources = []
        for ref, _ in candidates:
            candidate = self._resolve_literal_ref(ref, expression)
            if not isinstance(candidate, ResolvedValue):
                continue
            values.append(candidate.value)
            sources.append(f"{ref.module_name}.{ref.name}")
        unique_values = _unique_values(values)
        if not unique_values:
            return resolved
        source = "literal_ref:" + ",".join(sources)
        if len(unique_values) == 1:
            return ResolvedValue(unique_values[0], source, expression)
        return ResolvedValue(tuple(unique_values), source, expression)

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
    return LiteralIndex(values, config_object_value_assignments(repo))


def config_object_value_assignments(repo: RepoSnapshot) -> dict[ConfigObjectRef, tuple[ast.AST, ...]]:
    values_by_directory = _ini_option_values_by_directory(repo)
    assignments: dict[ConfigObjectRef, tuple[ast.AST, ...]] = {}
    for file_path in repo.python_files:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue
        option_values = values_by_directory.get(file_path.parent, {})
        if not option_values:
            continue
        module_name = module_name_for_path(repo, file_path)
        for object_name, attribute_path, option_name in _config_object_option_paths(tree):
            constants = tuple(ast.Constant(value=value) for value in option_values.get(option_name.casefold(), ()))
            if constants:
                assignments[ConfigObjectRef(module_name, object_name, attribute_path)] = constants
    return assignments


def _ini_option_values_by_directory(repo: RepoSnapshot) -> dict[Path, dict[str, tuple[str, ...]]]:
    values_by_directory: dict[Path, dict[str, list[str]]] = {}
    for path in sorted(repo.root.rglob("*.ini"), key=lambda candidate: str(candidate.relative_to(repo.root))):
        if not path.is_file():
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
        except configparser.Error:
            continue
        for section in parser.sections():
            for option, value in parser[section].items():
                values_by_directory.setdefault(path.parent, {}).setdefault(option.casefold(), []).append(value)
    return {
        directory: {option: tuple(_unique_strings(values)) for option, values in option_values.items()}
        for directory, option_values in values_by_directory.items()
    }


def _config_object_option_paths(tree: ast.AST) -> list[tuple[str, tuple[str, ...], str]]:
    if not isinstance(tree, ast.Module):
        return []
    module_aliases, constructor_aliases = _configparser_import_aliases(tree)
    module_parser_names = _module_configparser_instance_names(tree, module_aliases, constructor_aliases)
    class_infos: dict[str, ConfigClassInfo] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.ClassDef):
            continue
        class_infos[statement.name] = _class_config_info(
            statement,
            module_aliases,
            constructor_aliases,
            module_parser_names,
        )

    object_classes: dict[str, str] = {}
    for statement in tree.body:
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        class_name = _constructed_class_name(value)
        if class_name in class_infos:
            object_classes[target.id] = class_name

    paths: list[tuple[str, tuple[str, ...], str]] = []
    for object_name, class_name in object_classes.items():
        for attribute_path, option_name in _expand_config_class_paths(class_name, class_infos):
            paths.append((object_name, attribute_path, option_name))
    return paths


def _class_config_info(
    class_node: ast.ClassDef,
    module_aliases: set[str],
    constructor_aliases: set[str],
    module_parser_names: set[str],
) -> ConfigClassInfo:
    children: dict[str, ConfigChild] = {}
    options_by_root: dict[str, dict[str, str]] = {}
    params: tuple[str, ...] = ()
    local_parser_names: set[str] = set()
    for statement in class_node.body:
        if not isinstance(statement, ast.FunctionDef) or statement.name != "__init__":
            continue
        params = tuple(param.arg for param in statement.args.args[1:])
        local_parser_names = module_parser_names | _function_configparser_instance_names(
            statement,
            module_aliases,
            constructor_aliases,
        )
        for child in ast.walk(statement):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            value = child.value
            if value is None:
                continue
            for target in targets:
                attr = _self_attribute_name(target)
                if attr is None:
                    continue
                class_name = _constructed_class_name(value)
                if class_name:
                    children[attr] = ConfigChild(class_name=class_name, arg_roots=_call_arg_roots(value))
                    continue
                root_name, option_name = _configparser_option_ref(value)
                if option_name is not None:
                    options_by_root.setdefault(root_name, {})[attr] = option_name
    return ConfigClassInfo(
        params=params,
        local_parser_names=frozenset(local_parser_names),
        children=children,
        options_by_root=options_by_root,
    )


def _configparser_import_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    module_aliases: set[str] = set()
    constructor_aliases: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.name == "configparser":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ImportFrom) and statement.module == "configparser":
            for alias in statement.names:
                if alias.name == "ConfigParser":
                    constructor_aliases.add(alias.asname or alias.name)
    return module_aliases, constructor_aliases


def _function_configparser_instance_names(
    function_node: ast.FunctionDef,
    module_aliases: set[str],
    constructor_aliases: set[str],
) -> set[str]:
    parser_names: set[str] = set()
    for statement in function_node.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value = statement.value
        if value is None or not _is_configparser_constructor_call(value, module_aliases, constructor_aliases):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                parser_names.add(target.id)
    return parser_names


def _module_configparser_instance_names(
    tree: ast.Module,
    module_aliases: set[str],
    constructor_aliases: set[str],
) -> set[str]:
    parser_names: set[str] = set()
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value = statement.value
        if value is None or not _is_configparser_constructor_call(value, module_aliases, constructor_aliases):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                parser_names.add(target.id)
    return parser_names


def _expand_config_class_paths(
    class_name: str,
    class_infos: dict[str, ConfigClassInfo],
    prefix: tuple[str, ...] = (),
    allowed_roots: frozenset[str] | None = None,
    seen: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], str]]:
    if class_name in seen:
        return []
    info = class_infos.get(class_name)
    if info is None:
        return []
    active_roots = info.local_parser_names | (allowed_roots or frozenset())
    paths = [
        (prefix + (attr,), option)
        for root_name in active_roots
        for attr, option in info.options_by_root.get(root_name, {}).items()
    ]
    for attr, child in info.children.items():
        child_allowed_roots = set(class_infos.get(child.class_name, ConfigClassInfo((), frozenset(), {}, {})).local_parser_names)
        for arg_index, source_root in child.arg_roots:
            if source_root not in active_roots:
                continue
            child_info = class_infos.get(child.class_name)
            if child_info is None or arg_index >= len(child_info.params):
                continue
            child_allowed_roots.add(child_info.params[arg_index])
        paths.extend(
            _expand_config_class_paths(
                child.class_name,
                class_infos,
                prefix + (attr,),
                frozenset(child_allowed_roots),
                (*seen, class_name),
            )
        )
    return paths


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
    return _local_literal_assignments(function_node)


def local_literal_assignments_before(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    before_node: ast.AST,
) -> dict[str, ast.AST]:
    return _local_literal_assignments(function_node, before_node=before_node)


def _local_literal_assignments(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    before_node: ast.AST | None = None,
) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for statement in function_node.body:
        if before_node is not None and not node_starts_before(statement, before_node):
            break
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


def node_starts_before(node: ast.AST, reference: ast.AST) -> bool:
    node_line = getattr(node, "lineno", None)
    reference_line = getattr(reference, "lineno", None)
    if node_line is None or reference_line is None:
        return False
    node_col = getattr(node, "col_offset", 0)
    reference_col = getattr(reference, "col_offset", 0)
    return (node_line, node_col) < (reference_line, reference_col)


def bind_args(call_node: ast.Call, function_def: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST] | None:
    positional_params = [*function_def.args.posonlyargs, *function_def.args.args]
    keyword_params = {param.arg for param in [*function_def.args.args, *function_def.args.kwonlyargs]}
    bindings: dict[str, ast.AST] = {}
    if len(call_node.args) > len(positional_params) and function_def.args.vararg is None:
        return None
    for index, arg_node in enumerate(call_node.args):
        if index >= len(positional_params):
            break
        bindings[positional_params[index].arg] = arg_node
    for keyword in call_node.keywords:
        if keyword.arg is None:
            return None
        if keyword.arg not in keyword_params:
            return None
        if keyword.arg in bindings:
            return None
        bindings[keyword.arg] = keyword.value
    positional_defaults = function_def.args.defaults
    required_positional = positional_params[: len(positional_params) - len(positional_defaults)]
    for param in required_positional:
        if param.arg not in bindings:
            return None
    for param, default in zip(function_def.args.kwonlyargs, function_def.args.kw_defaults):
        if default is None and param.arg not in bindings:
            return None
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


def _constructed_class_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _constructed_class_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    return None


def _self_attribute_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "self":
        return None
    return node.attr


def _is_configparser_constructor_call(node: ast.AST, module_aliases: set[str], constructor_aliases: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return node.func.id in constructor_aliases
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id in module_aliases and node.func.attr == "ConfigParser"
    return False


def _call_arg_roots(node: ast.AST) -> tuple[tuple[int, str], ...]:
    if not isinstance(node, ast.Call):
        return ()
    roots = []
    for index, arg in enumerate(node.args):
        if isinstance(arg, ast.Name):
            roots.append((index, arg.id))
    return tuple(roots)


def _configparser_option_ref(node: ast.AST) -> tuple[str, str | None]:
    subscript_ref = _constant_subscript_ref(node)
    if subscript_ref is not None:
        return subscript_ref
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return "", None
    if node.func.attr not in {"get", "getint", "getfloat", "getboolean"}:
        return "", None
    if not isinstance(node.func.value, ast.Name):
        return "", None
    if len(node.args) < 2:
        return "", None
    if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
        return node.func.value.id, node.args[1].value
    return "", None


def _constant_subscript_ref(node: ast.AST) -> tuple[str, str] | None:
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
        return None
    if isinstance(node.value, ast.Subscript) and isinstance(node.value.value, ast.Name):
        return node.value.value.id, node.slice.value
    return None


def _unique_values(values: list[object]) -> list[object]:
    unique = []
    seen = set()
    for value in values:
        key = _stable_value_key(value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def _stable_value_key(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return ("scalar", value)
    if isinstance(value, set):
        return ("set", tuple(sorted((_stable_value_key(item) for item in value), key=repr)))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_stable_value_key(item) for item in value))
    if isinstance(value, dict):
        return (
            "dict",
            tuple(
                sorted(
                    ((_stable_value_key(key), _stable_value_key(item)) for key, item in value.items()),
                    key=repr,
                )
            ),
        )
    return ("object", type(value).__qualname__, repr(value))


def _unique_strings(values: list[str]) -> list[str]:
    unique = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arg_defaults(node.args)
        return

    def _visit_arg_defaults(self, args: ast.arguments) -> None:
        for default in [*args.defaults, *[default for default in args.kw_defaults if default is not None]]:
            self.visit(default)


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
