from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact, JsonObject
from source.kg.core.repo_source import RepoSnapshot


DJANGO_MODEL_FIELD_TYPES = {
    "AutoField",
    "BigAutoField",
    "BigIntegerField",
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "EmailField",
    "FloatField",
    "ForeignKey",
    "IntegerField",
    "ManyToManyField",
    "OneToOneField",
    "PositiveIntegerField",
    "SlugField",
    "TextField",
    "URLField",
    "UUIDField",
}
DJANGO_RELATION_FIELD_TYPES = {"ForeignKey", "OneToOneField", "ManyToManyField"}
FRAMEWORK_IMPORT_ROOTS = ("django", "rest_framework", "celery")


@dataclass(frozen=True)
class DjangoFrameworkExtraction:
    entities: list[Entity]
    facts: list[Fact]
    evidence: list[Evidence]
    recognized_framework: bool
    recognized_import_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ParsedFile:
    path: Path
    module_name: str
    tree: ast.AST


@dataclass(frozen=True)
class _SymbolRef:
    entity: Entity
    module_name: str
    qualname: str
    short_name: str
    node: ast.AST


def extract_django_framework_facts(
    repo: RepoSnapshot,
    parsed_files: dict[Path, ast.AST],
    *,
    tenant_id: str,
    source_system: str,
) -> DjangoFrameworkExtraction:
    files = [
        _ParsedFile(path=file_path, module_name=_module_name(repo, file_path), tree=tree)
        for file_path, tree in parsed_files.items()
    ]
    recognized_import_roots = tuple(sorted({root for file in files for root in _framework_import_roots(file.tree)}))
    files = [file for file in files if _has_framework_import(file.tree)]
    if not files:
        return DjangoFrameworkExtraction(entities=[], facts=[], evidence=[], recognized_framework=False)
    symbols = _collect_class_and_function_symbols(repo, files, tenant_id=tenant_id)
    symbols_by_full_name = {f"{symbol.module_name}.{symbol.qualname}": symbol for symbol in symbols}
    symbols_by_node_id = {id(symbol.node): symbol for symbol in symbols}

    model_symbols = _model_symbols(files, symbols_by_full_name)
    model_by_full_name = {f"{symbol.module_name}.{symbol.qualname}": symbol for symbol in model_symbols}
    model_by_short_name = _unique_by_short_name(model_symbols)
    model_by_app_label_and_short_name = _unique_by_app_label_and_short_name(model_symbols)

    serializer_symbols = _serializer_symbols(files, symbols_by_full_name)
    serializer_models = _serializer_model_targets(
        files,
        serializer_symbols,
        model_by_full_name,
        model_by_short_name,
        model_by_app_label_and_short_name,
    )
    serializer_by_full_name = {f"{symbol.module_name}.{symbol.qualname}": symbol for symbol in serializer_symbols}
    serializer_by_short_name = _unique_by_short_name(serializer_symbols)

    entities: list[Entity] = []
    facts: list[Fact] = []
    evidence: list[Evidence] = []
    seen_entities: set[str] = set()
    seen_facts: set[str] = set()

    def add_entity(entity: Entity, file_path: Path, line_start: int, line_end: int) -> None:
        if entity.entity_id in seen_entities:
            return
        seen_entities.add(entity.entity_id)
        entities.append(entity)
        evidence.append(
            Evidence(
                target_type="entity",
                target_id=entity.entity_id,
                derivation_class="deterministic_static",
                source_system=source_system,
                source_ref={"extractor": source_system, "entity_kind": entity.kind, "framework": "django"},
                bytes_ref=_bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    def add_fact(
        predicate: str,
        subject: Entity,
        object_: Entity,
        qualifier: JsonObject,
        file_path: Path,
        line_start: int,
        line_end: int,
    ) -> None:
        fact = Fact(predicate, subject.entity_id, object_.entity_id, qualifier)
        if fact.fact_id in seen_facts:
            return
        seen_facts.add(fact.fact_id)
        facts.append(fact)
        evidence.append(
            Evidence(
                target_type="fact",
                target_id=fact.fact_id,
                derivation_class="deterministic_static",
                source_system=source_system,
                source_ref={"extractor": source_system, "predicate": predicate, "framework": "django"},
                bytes_ref=_bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    for file in files:
        imports = _ImportResolver.from_module(file.module_name, file.tree)
        for node in ast.walk(file.tree):
            if isinstance(node, ast.ClassDef):
                full_name = f"{file.module_name}.{node.name}"
                model_symbol = model_by_full_name.get(full_name)
                if model_symbol is not None:
                    _emit_model_fields(
                        repo,
                        file,
                        node,
                        imports,
                        model_symbol,
                        model_by_full_name,
                        model_by_short_name,
                        model_by_app_label_and_short_name,
                        tenant_id,
                        add_entity,
                        add_fact,
                    )
                serializer_symbol = serializer_by_full_name.get(full_name)
                model_target = serializer_models.get(full_name)
                if serializer_symbol is not None and model_target is not None:
                    add_fact(
                        "SERIALIZES_MODEL",
                        serializer_symbol.entity,
                        model_target.entity,
                        {
                            "framework": "django",
                            "source_kind": "drf_model_serializer",
                            "model": model_target.short_name,
                            "fields": _serializer_meta_fields(node),
                        },
                        file.path,
                        getattr(node, "lineno", 1),
                        getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                    )
                view_symbol = symbols_by_full_name.get(full_name)
                if view_symbol is not None:
                    for model_target, source_kind in _viewset_model_targets(
                        node,
                        imports,
                        serializer_models,
                        serializer_by_full_name,
                        serializer_by_short_name,
                        model_by_full_name,
                        model_by_short_name,
                    ):
                        add_fact(
                            "HANDLES_MODEL",
                            view_symbol.entity,
                            model_target.entity,
                            {"framework": "django", "source_kind": source_kind, "model": model_target.short_name},
                            file.path,
                            getattr(node, "lineno", 1),
                            getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_celery_task(node, imports):
                    continue
                task_symbol = symbols_by_node_id.get(id(node))
                if task_symbol is None:
                    continue
                for model_target in _function_model_references(
                    node,
                    imports,
                    model_by_full_name,
                    model_by_short_name,
                    model_by_app_label_and_short_name,
                ):
                    add_fact(
                        "TASK_USES_MODEL",
                        task_symbol.entity,
                        model_target.entity,
                        {"framework": "celery", "source_kind": "task_model_reference", "model": model_target.short_name},
                        file.path,
                        getattr(node, "lineno", 1),
                        getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                    )

    return DjangoFrameworkExtraction(
        entities=entities,
        facts=facts,
        evidence=evidence,
        recognized_framework=True,
        recognized_import_roots=recognized_import_roots,
    )


def _emit_model_fields(
    repo: RepoSnapshot,
    file: _ParsedFile,
    node: ast.ClassDef,
    imports: "_ImportResolver",
    model_symbol: _SymbolRef,
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
    model_by_app_label_and_short_name: dict[tuple[str, str], _SymbolRef],
    tenant_id: str,
    add_entity,
    add_fact,
) -> None:
    for statement in node.body:
        target_name = _assignment_target_name(statement)
        value = _assignment_value(statement)
        if target_name is None or not isinstance(value, ast.Call):
            continue
        field_type = imports.django_field_type(value.func)
        if field_type is None:
            continue
        line = getattr(statement, "lineno", getattr(value, "lineno", getattr(node, "lineno", 1)))
        end_line = getattr(statement, "end_lineno", line)
        field_entity = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": tenant_id,
                "repo": repo.name,
                "module": file.module_name,
                "qualname": f"{node.name}.{target_name}",
                "symbol_kind": "django_field",
            },
            properties={
                "path": str(file.path.relative_to(repo.root)),
                "line": line,
                "end_line": end_line,
                "framework": "django",
                "field_type": field_type,
            },
        )
        add_entity(field_entity, file.path, line, end_line)
        add_fact(
            "DECLARES_FIELD",
            model_symbol.entity,
            field_entity,
            {"framework": "django", "field_name": target_name, "field_type": field_type},
            file.path,
            line,
            end_line,
        )
        if field_type in DJANGO_RELATION_FIELD_TYPES:
            relation_target = _relation_target(
                value,
                imports,
                model_by_full_name,
                model_by_short_name,
                model_by_app_label_and_short_name,
            )
            if relation_target is not None:
                add_fact(
                    "RELATES_TO_MODEL",
                    field_entity,
                    relation_target.entity,
                    {
                        "framework": "django",
                        "field_name": target_name,
                        "relation_type": field_type,
                        "target_model": relation_target.short_name,
                    },
                    file.path,
                    line,
                    end_line,
                )


def _collect_class_and_function_symbols(repo: RepoSnapshot, files: list[_ParsedFile], *, tenant_id: str) -> list[_SymbolRef]:
    symbols: list[_SymbolRef] = []
    for file in files:
        if not isinstance(file.tree, ast.Module):
            continue

        def visit(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    add_symbol(file, node, qualname, "class")
                    visit(node.body, qualname)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    symbol_kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                    if prefix:
                        symbol_kind = "method"
                    add_symbol(file, node, qualname, symbol_kind)

        def add_symbol(file: _ParsedFile, node: ast.AST, qualname: str, symbol_kind: str) -> None:
            entity = Entity(
                kind="CodeSymbol",
                identity={
                    "tenant_id": tenant_id,
                    "repo": repo.name,
                    "module": file.module_name,
                    "qualname": qualname,
                    "symbol_kind": symbol_kind,
                },
                properties={
                    "path": str(file.path.relative_to(repo.root)),
                    "line": getattr(node, "lineno", 1),
                    "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                },
            )
            symbols.append(_SymbolRef(entity, file.module_name, qualname, qualname.rsplit(".", 1)[-1], node))

        visit(file.tree.body)
    return symbols


def _model_symbols(files: list[_ParsedFile], symbols_by_full_name: dict[str, _SymbolRef]) -> list[_SymbolRef]:
    models: list[_SymbolRef] = []
    for file in files:
        imports = _ImportResolver.from_module(file.module_name, file.tree)
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(imports.is_django_model_base(base) for base in node.bases):
                continue
            symbol = symbols_by_full_name.get(f"{file.module_name}.{node.name}")
            if symbol is not None:
                models.append(symbol)
    return models


def _serializer_symbols(files: list[_ParsedFile], symbols_by_full_name: dict[str, _SymbolRef]) -> list[_SymbolRef]:
    serializers: list[_SymbolRef] = []
    for file in files:
        imports = _ImportResolver.from_module(file.module_name, file.tree)
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(imports.is_model_serializer_base(base) for base in node.bases):
                continue
            symbol = symbols_by_full_name.get(f"{file.module_name}.{node.name}")
            if symbol is not None:
                serializers.append(symbol)
    return serializers


def _serializer_model_targets(
    files: list[_ParsedFile],
    serializer_symbols: list[_SymbolRef],
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
    model_by_app_label_and_short_name: dict[tuple[str, str], _SymbolRef] | None = None,
) -> dict[str, _SymbolRef]:
    serializer_names = {f"{symbol.module_name}.{symbol.qualname}" for symbol in serializer_symbols}
    targets: dict[str, _SymbolRef] = {}
    for file in files:
        imports = _ImportResolver.from_module(file.module_name, file.tree)
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            full_name = f"{file.module_name}.{node.name}"
            if full_name not in serializer_names:
                continue
            meta = _inner_meta_class(node)
            if meta is None:
                continue
            for statement in meta.body:
                if _assignment_target_name(statement) != "model":
                    continue
                target = _resolve_model_expr(
                    _assignment_value(statement),
                    imports,
                    model_by_full_name,
                    model_by_short_name,
                    model_by_app_label_and_short_name,
                )
                if target is not None:
                    targets[full_name] = target
    return targets


def _viewset_model_targets(
    node: ast.ClassDef,
    imports: "_ImportResolver",
    serializer_models: dict[str, _SymbolRef],
    serializer_by_full_name: dict[str, _SymbolRef],
    serializer_by_short_name: dict[str, _SymbolRef],
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
) -> list[tuple[_SymbolRef, str]]:
    targets: list[tuple[_SymbolRef, str]] = []
    for statement in node.body:
        target_name = _assignment_target_name(statement)
        value = _assignment_value(statement)
        if target_name == "serializer_class":
            serializer = _resolve_serializer_expr(value, imports, serializer_by_full_name, serializer_by_short_name)
            if serializer is not None:
                model = serializer_models.get(f"{serializer.module_name}.{serializer.qualname}")
                if model is not None:
                    targets.append((model, "drf_serializer_class"))
        elif target_name == "queryset":
            model = _queryset_model(value, imports, model_by_full_name, model_by_short_name)
            if model is not None:
                targets.append((model, "django_queryset_model"))
    return _dedupe_model_targets(targets)


def _function_model_references(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: "_ImportResolver",
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
    model_by_app_label_and_short_name: dict[tuple[str, str], _SymbolRef],
) -> list[_SymbolRef]:
    refs: list[_SymbolRef] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr == "objects":
            target = _resolve_model_expr(
                child.value,
                imports,
                model_by_full_name,
                model_by_short_name,
                model_by_app_label_and_short_name,
            )
            if target is not None:
                refs.append(target)
        elif isinstance(child, ast.Call):
            target = _resolve_model_expr(
                child.func,
                imports,
                model_by_full_name,
                model_by_short_name,
                model_by_app_label_and_short_name,
            )
            if target is not None:
                refs.append(target)
    return _dedupe_symbols(refs)


def _relation_target(
    node: ast.Call,
    imports: "_ImportResolver",
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
    model_by_app_label_and_short_name: dict[tuple[str, str], _SymbolRef],
) -> _SymbolRef | None:
    candidate = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "to":
            candidate = keyword.value
            break
    return _resolve_model_expr(
        candidate,
        imports,
        model_by_full_name,
        model_by_short_name,
        model_by_app_label_and_short_name,
    )


def _resolve_model_expr(
    node: ast.AST | None,
    imports: "_ImportResolver",
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
    model_by_app_label_and_short_name: dict[tuple[str, str], _SymbolRef] | None = None,
) -> _SymbolRef | None:
    if isinstance(node, ast.Name):
        imported = imports.resolve_alias(node.id)
        if imported is not None:
            return model_by_full_name.get(imported)
        return model_by_short_name.get(node.id)
    if isinstance(node, ast.Attribute):
        full_name = _dotted_name(node)
        if full_name is not None:
            imported = imports.resolve_alias(full_name)
            if imported is not None:
                return model_by_full_name.get(imported)
            return model_by_full_name.get(full_name)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        if value == "self":
            return None
        if "." not in value:
            return model_by_short_name.get(value)
        app_label, model_name = value.split(".", 1)
        if "." in model_name:
            return None
        if model_by_app_label_and_short_name is None:
            return None
        return model_by_app_label_and_short_name.get((app_label, model_name))
    return None


def _resolve_serializer_expr(
    node: ast.AST | None,
    imports: "_ImportResolver",
    serializer_by_full_name: dict[str, _SymbolRef],
    serializer_by_short_name: dict[str, _SymbolRef],
) -> _SymbolRef | None:
    if isinstance(node, ast.Name):
        imported = imports.resolve_alias(node.id)
        if imported is not None:
            return serializer_by_full_name.get(imported)
        return serializer_by_short_name.get(node.id)
    imported = imports.resolve_alias(_dotted_name(node) or "")
    if imported is not None:
        return serializer_by_full_name.get(imported)
    return None


def _queryset_model(
    node: ast.AST | None,
    imports: "_ImportResolver",
    model_by_full_name: dict[str, _SymbolRef],
    model_by_short_name: dict[str, _SymbolRef],
) -> _SymbolRef | None:
    current = node
    while isinstance(current, (ast.Call, ast.Attribute)):
        if isinstance(current, ast.Call):
            current = current.func
        elif current.attr == "objects":
            return _resolve_model_expr(current.value, imports, model_by_full_name, model_by_short_name)
        else:
            current = current.value
    return None


def _is_celery_task(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: "_ImportResolver") -> bool:
    for decorator in node.decorator_list:
        candidate = decorator.func if isinstance(decorator, ast.Call) else decorator
        dotted = _dotted_name(candidate)
        resolved = imports.resolve_alias(dotted or "") or dotted
        if resolved in imports.celery_task_aliases:
            return True
        if isinstance(candidate, ast.Attribute) and candidate.attr == "task":
            owner_name = _dotted_name(candidate.value)
            if owner_name in imports.celery_app_aliases:
                return True
        if resolved == "celery.task":
            return True
    return False


def _serializer_meta_fields(node: ast.ClassDef) -> object:
    meta = _inner_meta_class(node)
    if meta is None:
        return None
    for statement in meta.body:
        if _assignment_target_name(statement) != "fields":
            continue
        value = _assignment_value(statement)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, (ast.List, ast.Tuple)):
            fields = []
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    fields.append(element.value)
            return fields
    return None


def _inner_meta_class(node: ast.ClassDef) -> ast.ClassDef | None:
    for statement in node.body:
        if isinstance(statement, ast.ClassDef) and statement.name == "Meta":
            return statement
    return None


def _assignment_target_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        return statement.targets[0].id
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id
    return None


def _assignment_value(statement: ast.stmt) -> ast.AST | None:
    if isinstance(statement, ast.Assign):
        return statement.value
    if isinstance(statement, ast.AnnAssign):
        return statement.value
    return None


def _unique_by_short_name(symbols: list[_SymbolRef]) -> dict[str, _SymbolRef]:
    counts = Counter(symbol.short_name for symbol in symbols)
    return {symbol.short_name: symbol for symbol in symbols if counts[symbol.short_name] == 1}


def _unique_by_app_label_and_short_name(symbols: list[_SymbolRef]) -> dict[tuple[str, str], _SymbolRef]:
    keys = [(_app_label_for_model_module(symbol.module_name), symbol.short_name) for symbol in symbols]
    counts = Counter(key for key in keys if key[0] is not None)
    return {
        (app_label, symbol.short_name): symbol
        for symbol, (app_label, _) in zip(symbols, keys, strict=False)
        if app_label is not None and counts[(app_label, symbol.short_name)] == 1
    }


def _app_label_for_model_module(module_name: str) -> str | None:
    parts = module_name.split(".")
    if "models" in parts:
        index = parts.index("models")
        if index > 0:
            return parts[index - 1]
    if len(parts) >= 2 and parts[-1] == "models":
        return parts[-2]
    return None


def _dedupe_symbols(symbols: list[_SymbolRef]) -> list[_SymbolRef]:
    seen = set()
    result = []
    for symbol in symbols:
        key = symbol.entity.entity_id
        if key in seen:
            continue
        seen.add(key)
        result.append(symbol)
    return result


def _dedupe_model_targets(targets: list[tuple[_SymbolRef, str]]) -> list[tuple[_SymbolRef, str]]:
    seen = set()
    result = []
    for symbol, source_kind in targets:
        key = (symbol.entity.entity_id, source_kind)
        if key in seen:
            continue
        seen.add(key)
        result.append((symbol, source_kind))
    return result


def _dotted_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _resolve_alias_with_map(aliases: dict[str, str], name: str) -> str | None:
    if not name:
        return None
    parts = name.split(".")
    head = parts[0]
    if head not in aliases:
        return None
    return ".".join([aliases[head], *parts[1:]])


def _module_name(repo: RepoSnapshot, file_path: Path) -> str:
    relative = file_path.relative_to(repo.root).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts) or repo.name


def _has_framework_import(tree: ast.AST) -> bool:
    return bool(_framework_import_roots(tree))


def _framework_import_roots(tree: ast.AST) -> tuple[str, ...]:
    if not isinstance(tree, ast.Module):
        return ()
    roots = set()
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom):
            root = _framework_import_root(statement.module or "")
            if root is not None:
                roots.add(root)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                root = _framework_import_root(alias.name)
                if root is not None:
                    roots.add(root)
    return tuple(sorted(roots))


def _is_framework_module(module_name: str) -> bool:
    return _framework_import_root(module_name) is not None


def _framework_import_root(module_name: str) -> str | None:
    for root in FRAMEWORK_IMPORT_ROOTS:
        if module_name == root or module_name.startswith(f"{root}."):
            return root
    return None


def _bytes_ref(repo: RepoSnapshot, file_path: Path, line_start: int, line_end: int) -> JsonObject:
    return {
        "repo": repo.name,
        "commit_sha": repo.commit_sha,
        "path": str(file_path.relative_to(repo.root)),
        "line_start": line_start,
        "line_end": line_end,
    }


class _ImportResolver:
    def __init__(
        self,
        module_name: str,
        aliases: dict[str, str],
        django_model_aliases: set[str],
        serializer_aliases: set[str],
        celery_task_aliases: set[str],
        celery_app_aliases: set[str],
    ) -> None:
        self.module_name = module_name
        self.aliases = aliases
        self.django_model_aliases = django_model_aliases
        self.serializer_aliases = serializer_aliases
        self.celery_task_aliases = celery_task_aliases
        self.celery_app_aliases = celery_app_aliases

    @classmethod
    def from_module(cls, module_name: str, tree: ast.AST) -> "_ImportResolver":
        aliases: dict[str, str] = {}
        django_model_aliases = {"models.Model"}
        serializer_aliases = {"serializers.ModelSerializer"}
        celery_task_aliases: set[str] = set()
        celery_app_aliases: set[str] = set()
        if not isinstance(tree, ast.Module):
            return cls(
                module_name,
                aliases,
                django_model_aliases,
                serializer_aliases,
                celery_task_aliases,
                celery_app_aliases,
            )
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom):
                source_module = _resolve_import_from_module(module_name, statement)
                for alias in statement.names:
                    local = alias.asname or alias.name
                    full = f"{source_module}.{alias.name}" if source_module else alias.name
                    aliases[local] = full
                    if source_module == "django.db" and alias.name == "models":
                        aliases[local] = "django.db.models"
                    if source_module == "django.db.models":
                        if alias.name == "Model":
                            django_model_aliases.add(local)
                        if alias.name in DJANGO_MODEL_FIELD_TYPES:
                            aliases[local] = f"django.db.models.{alias.name}"
                    if source_module == "rest_framework" and alias.name == "serializers":
                        aliases[local] = "rest_framework.serializers"
                    if source_module == "rest_framework.serializers" and alias.name == "ModelSerializer":
                        serializer_aliases.add(local)
                    if source_module == "celery" and alias.name == "shared_task":
                        aliases[local] = "celery.shared_task"
                        celery_task_aliases.add("celery.shared_task")
                    if source_module == "celery" and alias.name == "task":
                        aliases[local] = "celery.task"
                        celery_task_aliases.add("celery.task")
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    local = alias.asname or alias.name.split(".", 1)[0]
                    aliases[local] = alias.name
        for statement in tree.body:
            target_name = _assignment_target_name(statement)
            value = _assignment_value(statement)
            if target_name is None or not isinstance(value, ast.Call):
                continue
            factory_name = _dotted_name(value.func)
            resolved_factory = aliases.get(factory_name or "") or (
                _resolve_alias_with_map(aliases, factory_name or "") if factory_name else None
            )
            if resolved_factory == "celery.Celery":
                celery_app_aliases.add(target_name)
        return cls(
            module_name,
            aliases,
            django_model_aliases,
            serializer_aliases,
            celery_task_aliases,
            celery_app_aliases,
        )

    def resolve_alias(self, name: str) -> str | None:
        return _resolve_alias_with_map(self.aliases, name)

    def is_django_model_base(self, node: ast.AST) -> bool:
        dotted = _dotted_name(node)
        if dotted is None:
            return False
        resolved = self.resolve_alias(dotted) or dotted
        return resolved in {"django.db.models.Model", *self.django_model_aliases}

    def is_model_serializer_base(self, node: ast.AST) -> bool:
        dotted = _dotted_name(node)
        if dotted is None:
            return False
        resolved = self.resolve_alias(dotted) or dotted
        return resolved in {"rest_framework.serializers.ModelSerializer", *self.serializer_aliases}

    def django_field_type(self, node: ast.AST) -> str | None:
        dotted = _dotted_name(node)
        if dotted is None:
            return None
        resolved = self.resolve_alias(dotted) or dotted
        field_type = resolved.rsplit(".", 1)[-1]
        if resolved.startswith("django.db.models.") and field_type in DJANGO_MODEL_FIELD_TYPES:
            return field_type
        if field_type in DJANGO_MODEL_FIELD_TYPES and dotted in self.aliases:
            return field_type
        return None


def _resolve_import_from_module(current_module: str, statement: ast.ImportFrom) -> str:
    module = statement.module or ""
    if statement.level <= 0:
        return module
    parts = current_module.split(".")
    package_parts = parts[: max(0, len(parts) - statement.level)]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(part for part in package_parts if part)
