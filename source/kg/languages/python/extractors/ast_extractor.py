from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib
from typing import Literal
import warnings

from source.kg.core.models import Coverage, Entity, Evidence, EvidenceDerivationClass, Fact, JsonObject
from source.kg.languages.python.extractors.authz_surface import extract_python_authz_surface
from source.kg.languages.python.extractors.dataflow import (
    LiteralIndex,
    LiteralRef,
    body_call_nodes,
    config_object_value_assignments,
    module_literal_assignments,
)
from source.kg.languages.python.extractors.django_framework import extract_django_framework_facts
from source.kg.languages.python.extractors.transport_extractor import (
    extract_transport_events,
    module_transport_context,
)
from source.kg.languages.python.extractors.receiver_calls import (
    IndexedSymbol,
    PythonReceiverCallIndex,
    PythonReceiverCallResolver,
    ResolvedPythonCalls,
)
from source.kg.languages.python.extractors.runtime_calls import (
    RuntimeCall,
    collect_builtin_runtime_calls,
    module_bound_builtin_names,
)
from source.kg.languages.python.extractors.source_context import source_excerpt, source_line
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.core.tenant import resolve_tenant_id
from source.kg.languages.python.normalization.imports import NormalizedImport, PythonImportNormalizer
from source.kg.core.repo_source import RepoSnapshot


@dataclass
class KgBuild:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    support_facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolDef:
    entity: Entity
    module_name: str
    qualname: str
    symbol_kind: str
    line: int
    end_line: int


FunctionDefNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class ParsedPythonFile:
    tree: ast.AST | None
    line_count: int
    source_text: str
    syntax_error: SyntaxError | None = None


class PythonAstExtractor:
    source_system = "python_ast_v0"

    def __init__(self, *, include_transport: bool = True) -> None:
        self.include_transport = include_transport

    def extract(self, repo: RepoSnapshot) -> KgBuild:
        return self.extract_with_context(repo, None)

    def extract_with_context(self, repo: RepoSnapshot, ctx: ExtractionContext | None) -> KgBuild:
        tenant_id = ctx.tenant_id if ctx is not None else resolve_tenant_id()
        build = KgBuild()
        repo_entity = self._repo_entity(repo, tenant_id)
        service_entity = self._service_entity(repo, tenant_id)
        build.entities.extend([repo_entity, service_entity])
        service_line = self._service_definition_line(repo)
        build.evidence.extend(
            [
                self._repo_evidence(repo, repo_entity),
                self._service_evidence(repo, service_entity, service_line=service_line),
            ]
        )
        self._add_fact(
            build,
            "DEFINED_IN",
            service_entity,
            repo_entity,
            repo,
            repo.root / "pyproject.toml",
            service_line,
            service_line,
        )
        import_normalizer = PythonImportNormalizer(repo)
        parsed_files = self._parsed_files(repo, ctx)
        literal_index = self._literal_index_for_context(repo, parsed_files, ctx)
        collected_symbols: dict[Path, tuple[list[SymbolDef], dict[str, FunctionDefNode]]] = {}
        all_symbols: list[SymbolDef] = []
        for file_path, parsed in parsed_files.items():
            if parsed.tree is None:
                continue
            module_name = self._module_name(repo, file_path)
            symbols, function_defs = self._collect_symbols(repo, file_path, module_name, parsed.tree, tenant_id)
            collected_symbols[file_path] = (symbols, function_defs)
            all_symbols.extend(symbols)
        receiver_call_index = PythonReceiverCallIndex(self._indexed_symbol(symbol) for symbol in all_symbols)
        emitted_runtime_symbol_ids: set[str] = set()

        for file_path in repo.files_by_language.get("python", ()):
            self._extract_file(
                repo,
                file_path,
                parsed_files[file_path],
                collected_symbols.get(file_path, ([], {})),
                receiver_call_index,
                repo_entity,
                service_entity,
                import_normalizer,
                literal_index,
                build,
                ctx,
                tenant_id,
                emitted_runtime_symbol_ids,
            )

        parsed_trees = {
            file_path: parsed.tree
            for file_path, parsed in parsed_files.items()
            if parsed.tree is not None
        }
        django_framework = extract_django_framework_facts(
            repo,
            parsed_trees,
            tenant_id=tenant_id,
            source_system=self.source_system,
        )
        build.entities.extend(django_framework.entities)
        build.support_facts.extend(django_framework.facts)
        build.evidence.extend(django_framework.evidence)
        authz_surface = extract_python_authz_surface(
            repo,
            parsed_trees,
            tenant_id=tenant_id,
            source_system=self.source_system,
        )
        build.entities.extend(authz_surface.entities)
        build.support_facts.extend(authz_surface.facts)
        build.evidence.extend(authz_surface.evidence)
        # Coverage predicates describe extractor scope; support fact predicates remain separately allowlisted.
        if django_framework.facts or authz_surface.facts:
            build.coverage.append(
                Coverage(
                    tenant_id=tenant_id,
                    predicate="FRAMEWORK_IMPACT",
                    scope_ref={
                        "repo": repo.name,
                        "language": "python",
                        "framework_family": "python_framework_stack",
                        "framework_import_roots": sorted(
                            set(django_framework.recognized_import_roots)
                            | set(authz_surface.recognized_import_roots)
                        ),
                    },
                    state="instrumented",
                    source_system=self.source_system,
                )
            )
        elif django_framework.recognized_framework or authz_surface.recognized_framework:
            build.coverage.append(
                Coverage(
                    tenant_id=tenant_id,
                    predicate="FRAMEWORK_IMPACT",
                    scope_ref={
                        "repo": repo.name,
                        "language": "python",
                        "framework_family": "python_framework_stack",
                        "framework_import_roots": sorted(
                            set(django_framework.recognized_import_roots)
                            | set(authz_surface.recognized_import_roots)
                        ),
                        "reason": "recognized_framework_without_static_framework_impact_facts",
                    },
                    state="partially_instrumented",
                    source_system=self.source_system,
                )
            )

        build.coverage.append(
            Coverage(
                tenant_id=tenant_id,
                predicate="CALLS",
                scope_ref={"repo": repo.name, "language": "python", "path_prefix": "."},
                state="instrumented",
                source_system=self.source_system,
            )
        )
        return build

    def extract_transport_events_only(self, repo: RepoSnapshot, ctx: ExtractionContext | None = None) -> KgBuild:
        tenant_id = ctx.tenant_id if ctx is not None else resolve_tenant_id()
        build = KgBuild()
        import_normalizer = PythonImportNormalizer(repo)
        parsed_files = self._parsed_files(repo, ctx)
        literal_index = self._literal_index_for_context(repo, parsed_files, ctx)
        for file_path in repo.files_by_language.get("python", ()):
            self._extract_transport_file(
                repo,
                file_path,
                parsed_files[file_path],
                import_normalizer,
                literal_index,
                build,
                ctx,
                tenant_id,
            )
        return build

    def _parsed_files(self, repo: RepoSnapshot, ctx: ExtractionContext | None) -> dict[Path, ParsedPythonFile]:
        if ctx is None:
            return {file_path: self._parse_file(file_path) for file_path in repo.files_by_language.get("python", ())}
        key = self._repo_cache_key(repo)
        python_cache = ctx.parsed_by_language.setdefault("python", {})
        cached = python_cache.get(key)
        if cached is None:
            cached = {file_path: self._parse_file(file_path) for file_path in repo.files_by_language.get("python", ())}
            python_cache[key] = cached
        return cached

    def _literal_index_for_context(
        self,
        repo: RepoSnapshot,
        parsed_files: dict[Path, ParsedPythonFile],
        ctx: ExtractionContext | None,
    ) -> LiteralIndex:
        if ctx is None:
            return self._literal_index(repo, parsed_files)
        key = self._repo_cache_key(repo)
        literal_cache = ctx.literal_indexes_by_language.setdefault("python", {})
        cached = literal_cache.get(key)
        if cached is None:
            cached = self._literal_index(repo, parsed_files)
            literal_cache[key] = cached
        return cached

    def _repo_cache_key(self, repo: RepoSnapshot) -> str:
        return f"{repo.root}:{repo.commit_sha}"

    def _extract_file(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        parsed: ParsedPythonFile,
        collected_symbols: tuple[list[SymbolDef], dict[str, FunctionDefNode]],
        receiver_call_index: PythonReceiverCallIndex,
        repo_entity: Entity,
        service_entity: Entity,
        import_normalizer: PythonImportNormalizer,
        literal_index: LiteralIndex,
        build: KgBuild,
        ctx: ExtractionContext | None,
        tenant_id: str,
        emitted_runtime_symbol_ids: set[str],
    ) -> None:
        tree = parsed.tree
        if tree is None:
            exc = parsed.syntax_error
            build.coverage.append(
                Coverage(
                    tenant_id=tenant_id,
                    predicate="PARSES",
                    scope_ref={
                        "repo": repo.name,
                        "language": "python",
                        "path": str(file_path.relative_to(repo.root)),
                    },
                    state="uninstrumented",
                    source_system=self.source_system,
                )
            )
            build.evidence.append(
                Evidence(
                    target_type="entity",
                    target_id=repo_entity.entity_id,
                    derivation_class="deterministic_static",
                    source_system=self.source_system,
                    source_ref={
                        "extractor": self.source_system,
                        "error": "syntax_error",
                        "message": str(exc) if exc is not None else "unknown syntax error",
                    },
                    bytes_ref=self._bytes_ref(
                        repo,
                        file_path,
                        getattr(exc, "lineno", 1) or 1,
                        getattr(exc, "lineno", 1) or 1,
                    ),
                    confidence=1.0,
                )
            )
            return
        module_name = self._module_name(repo, file_path)
        module_entity = Entity(
            kind="CodeModule",
            identity={"tenant_id": tenant_id, "repo": repo.name, "module": module_name},
            properties={"path": str(file_path.relative_to(repo.root))},
        )
        build.entities.append(module_entity)
        build.evidence.append(self._entity_evidence(repo, module_entity, file_path, 1, max(1, parsed.line_count)))
        self._add_fact(build, "DEFINED_IN", module_entity, repo_entity, repo, file_path, 1, 1)
        self._add_fact(build, "IMPLEMENTS", module_entity, service_entity, repo, file_path, 1, 1)

        symbols, function_defs = collected_symbols
        by_qualname = {symbol.qualname: symbol for symbol in symbols}
        by_short_name = {symbol.qualname.rsplit(".", 1)[-1]: symbol for symbol in symbols}
        function_defs_by_short_name = {
            symbol.qualname.rsplit(".", 1)[-1]: function_defs[symbol.qualname]
            for symbol in symbols
            if symbol.symbol_kind in {"function", "async_function"} and symbol.qualname in function_defs
        }
        for symbol in symbols:
            build.entities.append(symbol.entity)
            build.evidence.append(self._entity_evidence(repo, symbol.entity, file_path, symbol.line, symbol.end_line))
            self._add_fact(build, "DEFINED_IN", symbol.entity, module_entity, repo, file_path, symbol.line, symbol.end_line)

        imports = import_normalizer.collect(tree, module_name)
        if ctx is not None:
            import_roots = ctx.import_roots_by_language.setdefault("python", set())
            import_roots.update(import_ref.import_root for import_ref in imports)
        imports_by_root: dict[str, NormalizedImport] = {}
        for import_ref in imports:
            dependency_entity = self._dependency_entity(repo, import_ref, tenant_id)
            build.entities.append(dependency_entity)
            build.evidence.append(self._entity_evidence(repo, dependency_entity, file_path, import_ref.line, import_ref.line))
            self._add_fact(
                build,
                "IMPORTS",
                module_entity,
                dependency_entity,
                repo,
                file_path,
                import_ref.line,
                import_ref.line,
                qualifier=self._import_qualifier(import_ref),
            )
            imports_by_root.setdefault(import_ref.import_root, import_ref)

        module_context = module_transport_context(tree if isinstance(tree, ast.Module) else None, imports)
        emitted_call_keys: set[tuple[str, str, int, int]] = set()
        receiver_resolver = PythonReceiverCallResolver(
            index=receiver_call_index,
            current_module=module_name,
            imports=imports,
        )
        if isinstance(tree, ast.Module):
            module_builtin_shadows = module_bound_builtin_names(tree)
            self._add_resolved_python_calls(
                build,
                emitted_call_keys,
                receiver_resolver.calls_in_body(tree.body, caller=module_entity, source_text=parsed.source_text),
                repo,
                file_path,
            )
        else:
            module_builtin_shadows = set()
        for caller_node in ast.walk(tree):
            if not isinstance(caller_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller_name = self._qualname_for_node(tree, caller_node)
            caller = by_qualname.get(caller_name)
            if caller is None:
                continue
            for call_node in body_call_nodes(caller_node):
                call_name = self._call_name(call_node.func)
                if not call_name:
                    continue
                line = getattr(call_node, "lineno", caller.line)
                local_callee = (
                    by_short_name.get(call_name.split(".")[-1])
                    if self._can_bind_call_by_short_name(call_node.func)
                    else None
                )
                if local_callee is not None and local_callee.symbol_kind == "class":
                    continue
                if local_callee is not None and local_callee.entity.entity_id != caller.entity.entity_id:
                    self._add_call_fact_once(
                        build,
                        emitted_call_keys,
                        caller.entity,
                        local_callee.entity,
                        repo,
                        file_path,
                        line,
                        getattr(call_node, "col_offset", -1),
                        qualifier=self._call_site_qualifier(call_node, parsed.source_text),
                    )
                    continue
                root = call_name.split(".", 1)[0]
                if receiver_resolver.class_from_constructor(call_node.func) is not None:
                    continue
                if root in imports_by_root:
                    package_entity = self._dependency_entity(repo, imports_by_root[root], tenant_id)
                    build.entities.append(package_entity)
                    self._add_call_fact_once(
                        build,
                        emitted_call_keys,
                        caller.entity,
                        package_entity,
                        repo,
                        file_path,
                        line,
                        getattr(call_node, "col_offset", -1),
                        qualifier=self._call_site_qualifier(call_node, parsed.source_text, {"call": call_name}),
                    )
            self._add_runtime_builtin_calls(
                build,
                emitted_call_keys,
                collect_builtin_runtime_calls(
                    caller_node,
                    module_bound_names=module_builtin_shadows,
                    source_text=parsed.source_text,
                ),
                caller.entity,
                repo,
                file_path,
                tenant_id,
                emitted_runtime_symbol_ids,
            )
            self._add_resolved_python_calls(
                build,
                emitted_call_keys,
                receiver_resolver.calls_in_body(
                    caller_node.body,
                    caller=caller.entity,
                    shadowed_names=self._function_bound_names(caller_node),
                    local_imports_shadow=True,
                    source_text=parsed.source_text,
                ),
                repo,
                file_path,
            )
            if self.include_transport:
                extract_transport_events(
                    repo,
                    file_path,
                    caller,
                    caller_node,
                    imports,
                    literal_index,
                    build,
                    self.source_system,
                    self._add_entity_evidence,
                    self._add_fact,
                    function_defs=function_defs_by_short_name,
                    module_node=tree if isinstance(tree, ast.Module) else None,
                    module_context=module_context,
                    tenant_id=tenant_id,
                )

    def _extract_transport_file(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        parsed: ParsedPythonFile,
        import_normalizer: PythonImportNormalizer,
        literal_index: LiteralIndex,
        build: KgBuild,
        ctx: ExtractionContext | None,
        tenant_id: str,
    ) -> None:
        tree = parsed.tree
        if tree is None:
            return
        module_name = self._module_name(repo, file_path)
        imports = import_normalizer.collect(tree, module_name)
        if ctx is not None:
            import_roots = ctx.import_roots_by_language.setdefault("python", set())
            import_roots.update(import_ref.import_root for import_ref in imports)
        symbols, function_defs = self._collect_symbols(repo, file_path, module_name, tree, tenant_id)
        by_qualname = {symbol.qualname: symbol for symbol in symbols}
        function_defs_by_short_name = {
            symbol.qualname.rsplit(".", 1)[-1]: function_defs[symbol.qualname]
            for symbol in symbols
            if symbol.symbol_kind in {"function", "async_function"} and symbol.qualname in function_defs
        }
        module_context = module_transport_context(tree if isinstance(tree, ast.Module) else None, imports)
        for caller_node in ast.walk(tree):
            if not isinstance(caller_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller_name = self._qualname_for_node(tree, caller_node)
            caller = by_qualname.get(caller_name)
            if caller is None:
                continue
            extract_transport_events(
                repo,
                file_path,
                caller,
                caller_node,
                imports,
                literal_index,
                build,
                self.source_system,
                self._add_entity_evidence,
                self._add_fact,
                function_defs=function_defs_by_short_name,
                module_node=tree if isinstance(tree, ast.Module) else None,
                module_context=module_context,
                tenant_id=tenant_id,
            )

    def _parse_file(self, file_path: Path) -> ParsedPythonFile:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        line_count = len(source.splitlines())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            return ParsedPythonFile(tree=None, line_count=line_count, source_text=source, syntax_error=exc)
        return ParsedPythonFile(tree=tree, line_count=line_count, source_text=source)

    def _literal_index(self, repo: RepoSnapshot, parsed_files: dict[Path, ParsedPythonFile]) -> LiteralIndex:
        values: dict[LiteralRef, ast.AST] = {}
        parsed_trees: dict[Path, ast.AST] = {}
        for file_path, parsed in parsed_files.items():
            if parsed.tree is None:
                continue
            parsed_trees[file_path] = parsed.tree
            module_name = self._module_name(repo, file_path)
            for name, value in module_literal_assignments(parsed.tree).items():
                values[LiteralRef(module_name, name)] = value
        config_values, config_sources = config_object_value_assignments(repo, parsed_trees)
        return LiteralIndex(values, config_values, config_sources)

    def _collect_symbols(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        module_name: str,
        tree: ast.AST,
        tenant_id: str,
    ) -> tuple[list[SymbolDef], dict[str, FunctionDefNode]]:
        symbols: list[SymbolDef] = []
        function_defs: dict[str, FunctionDefNode] = {}

        def visit(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    symbols.append(self._symbol(repo, file_path, module_name, qualname, "class", node, tenant_id))
                    visit(node.body, qualname)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                    if prefix:
                        kind = "method"
                    symbols.append(self._symbol(repo, file_path, module_name, qualname, kind, node, tenant_id))
                    function_defs[qualname] = node

        if isinstance(tree, ast.Module):
            visit(tree.body)
        return symbols, function_defs

    def _indexed_symbol(self, symbol: SymbolDef) -> IndexedSymbol:
        return IndexedSymbol(
            entity=symbol.entity,
            module_name=symbol.module_name,
            qualname=symbol.qualname,
            symbol_kind=symbol.symbol_kind,
        )

    def _symbol(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        module_name: str,
        qualname: str,
        symbol_kind: str,
        node: ast.AST,
        tenant_id: str,
    ) -> SymbolDef:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)
        entity = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": tenant_id,
                "repo": repo.name,
                "module": module_name,
                "qualname": qualname,
                "symbol_kind": symbol_kind,
            },
            properties={"path": str(file_path.relative_to(repo.root)), "line": line},
        )
        return SymbolDef(entity, module_name, qualname, symbol_kind, line, end_line)

    def _add_call_fact_once(
        self,
        build: KgBuild,
        emitted_call_keys: set[tuple[str, str, int, int]],
        subject: Entity,
        object_: Entity,
        repo: RepoSnapshot,
        file_path: Path,
        line: int,
        column: int,
        qualifier: JsonObject | None = None,
    ) -> None:
        key = (subject.entity_id, object_.entity_id, line, column)
        if key in emitted_call_keys:
            return
        emitted_call_keys.add(key)
        self._add_fact(build, "CALLS", subject, object_, repo, file_path, line, line, qualifier=qualifier)

    def _call_site_qualifier(self, call_node: ast.Call, source_text: str, base: JsonObject | None = None) -> JsonObject:
        qualifier = dict(base or {})
        line_text = source_line(source_text, getattr(call_node, "lineno", 1))
        excerpt = source_excerpt(source_text, call_node)
        if line_text is not None:
            qualifier["source_line"] = line_text
        if excerpt is not None:
            qualifier["source_excerpt"] = excerpt
        return qualifier

    def _source_qualifier(self, line_text: str | None, excerpt: str | None) -> JsonObject:
        qualifier: JsonObject = {}
        if line_text is not None:
            qualifier["source_line"] = line_text
        if excerpt is not None:
            qualifier["source_excerpt"] = excerpt
        return qualifier

    def _add_resolved_python_calls(
        self,
        build: KgBuild,
        emitted_call_keys: set[tuple[str, str, int, int]],
        resolved_calls: ResolvedPythonCalls,
        repo: RepoSnapshot,
        file_path: Path,
    ) -> None:
        for constructor_call in resolved_calls.constructor_calls:
            self._add_call_fact_once(
                build,
                emitted_call_keys,
                constructor_call.caller,
                constructor_call.callee,
                repo,
                file_path,
                constructor_call.line,
                constructor_call.column,
                qualifier={
                    "call": constructor_call.raw_call,
                    "constructor_class": constructor_call.constructor_class,
                    "resolution_kind": "python_constructor_call",
                    **self._source_qualifier(constructor_call.source_line, constructor_call.source_excerpt),
                },
            )
        for receiver_call in resolved_calls.receiver_calls:
            self._add_call_fact_once(
                build,
                emitted_call_keys,
                receiver_call.caller,
                receiver_call.callee,
                repo,
                file_path,
                receiver_call.line,
                receiver_call.column,
                qualifier={
                    "call": receiver_call.raw_call,
                    "receiver": receiver_call.receiver_name,
                    "receiver_class": receiver_call.receiver_class,
                    "resolution_kind": "python_local_instance_receiver",
                    **self._source_qualifier(receiver_call.source_line, receiver_call.source_excerpt),
                },
            )

    def _add_runtime_builtin_calls(
        self,
        build: KgBuild,
        emitted_call_keys: set[tuple[str, str, int, int]],
        runtime_calls: list[RuntimeCall],
        caller: Entity,
        repo: RepoSnapshot,
        file_path: Path,
        tenant_id: str,
        emitted_runtime_symbol_ids: set[str],
    ) -> None:
        for runtime_call in runtime_calls:
            callee = self._external_symbol(repo, runtime_call.name, tenant_id)
            if callee.entity_id not in emitted_runtime_symbol_ids:
                emitted_runtime_symbol_ids.add(callee.entity_id)
                build.entities.append(callee)
                build.evidence.append(self._external_symbol_evidence(callee))
            self._add_call_fact_once(
                build,
                emitted_call_keys,
                caller,
                callee,
                repo,
                file_path,
                runtime_call.line,
                runtime_call.column,
                qualifier={
                    "call": runtime_call.raw_call,
                    "runtime": "python",
                    "module": "builtins",
                    "resolution_kind": "python_builtin_call",
                    **self._source_qualifier(runtime_call.source_line, runtime_call.source_excerpt),
                },
            )

    def _function_bound_names(self, node: FunctionDefNode) -> set[str]:
        names = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        if node.args.vararg is not None:
            names.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            names.add(node.args.kwarg.arg)
        return names

    def _add_fact(
        self,
        build: KgBuild,
        predicate: str,
        subject: Entity,
        object_: Entity,
        repo: RepoSnapshot,
        file_path: Path,
        line_start: int,
        line_end: int,
        qualifier: JsonObject | None = None,
        derivation_class: EvidenceDerivationClass = "deterministic_static",
        canonical_status: Literal["canonical", "candidate", "demoted"] = "canonical",
    ) -> None:
        fact = Fact(
            predicate=predicate,
            subject_id=subject.entity_id,
            object_id=object_.entity_id,
            qualifier=qualifier or {},
            canonical_status=canonical_status,
        )
        build.facts.append(fact)
        build.evidence.append(
            Evidence(
                target_type="fact",
                target_id=fact.fact_id,
                derivation_class=derivation_class,
                source_system=self.source_system,
                source_ref={"extractor": self.source_system, "predicate": predicate},
                bytes_ref=self._bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    def _repo_entity(self, repo: RepoSnapshot, tenant_id: str) -> Entity:
        return Entity(
            kind="Repo",
            identity={"tenant_id": tenant_id, "host": "local", "owner": repo.owner, "name": repo.name},
            properties={"path": str(repo.root), "commit_sha": repo.commit_sha},
        )

    def _service_entity(self, repo: RepoSnapshot, tenant_id: str) -> Entity:
        return Entity(
            kind="Service",
            identity={
                "tenant_id": tenant_id,
                "namespace": "default",
                "repo": repo.name,
                "slug": self._service_slug(repo),
            },
            properties={"repo": repo.name},
        )

    def _dependency_entity(self, repo: RepoSnapshot, import_ref: NormalizedImport, tenant_id: str) -> Entity:
        if import_ref.category in {"internal_module", "relative_internal_module"}:
            return Entity(
                kind="CodeModule",
                identity={"tenant_id": tenant_id, "repo": repo.name, "module": import_ref.target_name},
                properties={"dependency_category": import_ref.category},
            )
        return self._external_package(repo, import_ref, tenant_id)

    def _external_package(self, repo: RepoSnapshot, import_ref: NormalizedImport, tenant_id: str) -> Entity:
        return Entity(
            kind="ExternalPackage",
            identity={"tenant_id": tenant_id, "repo": repo.name, "name": import_ref.target_name},
            properties={
                "category": import_ref.category,
                "import_root": import_ref.import_root,
                "distribution_name": import_ref.distribution_name,
            },
        )

    def _external_symbol(self, repo: RepoSnapshot, name: str, tenant_id: str) -> Entity:
        return Entity(
            kind="ExternalSymbol",
            identity={
                "tenant_id": tenant_id,
                "repo": repo.name,
                "language": "python",
                "module": "builtins",
                "name": name,
                "symbol_kind": "builtin",
            },
            properties={"category": "python_builtin"},
        )

    def _external_symbol_evidence(self, entity: Entity) -> Evidence:
        identity = entity.identity
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_static",
            source_system="python_runtime",
            source_ref={
                "language": identity.get("language"),
                "module": identity.get("module"),
                "name": identity.get("name"),
                "symbol_kind": identity.get("symbol_kind"),
            },
            confidence=1.0,
        )

    def _import_qualifier(self, import_ref: NormalizedImport) -> JsonObject:
        return {
            "raw_import": import_ref.raw_import,
            "import_root": import_ref.import_root,
            "distribution_name": import_ref.distribution_name,
            "category": import_ref.category,
            "module_name": import_ref.module_name,
            "imported_names": list(import_ref.imported_names),
            "alias": import_ref.alias,
        }

    def _repo_evidence(self, repo: RepoSnapshot, entity: Entity) -> Evidence:
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="git",
            source_ref={"repo_path": str(repo.root), "commit_sha": repo.commit_sha},
            confidence=1.0,
        )

    def _service_evidence(self, repo: RepoSnapshot, entity: Entity, *, service_line: int) -> Evidence:
        pyproject = repo.root / "pyproject.toml"
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="pyproject",
            source_ref={"package_name": self._package_name(repo)},
            bytes_ref=self._bytes_ref(repo, pyproject, service_line, service_line) if pyproject.exists() else None,
            confidence=1.0,
        )

    def _entity_evidence(self, repo: RepoSnapshot, entity: Entity, file_path: Path, line_start: int, line_end: int) -> Evidence:
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="deterministic_static",
            source_system=self.source_system,
            source_ref={"extractor": self.source_system, "entity_kind": entity.kind},
            bytes_ref=self._bytes_ref(repo, file_path, line_start, line_end),
            confidence=1.0,
        )

    def _add_entity_evidence(
        self,
        build: KgBuild,
        repo: RepoSnapshot,
        entity: Entity,
        file_path: Path,
        line_start: int,
        line_end: int,
    ) -> None:
        build.entities.append(entity)
        build.evidence.append(self._entity_evidence(repo, entity, file_path, line_start, line_end))

    def _bytes_ref(self, repo: RepoSnapshot, file_path: Path, line_start: int, line_end: int) -> JsonObject:
        return {
            "repo": repo.name,
            "commit_sha": repo.commit_sha,
            "path": str(file_path.relative_to(repo.root)),
            "line_start": line_start,
            "line_end": line_end,
        }

    def _service_slug(self, repo: RepoSnapshot) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self._package_name(repo).lower()).strip("-") or repo.name

    def _service_definition_line(self, repo: RepoSnapshot) -> int:
        pyproject = repo.root / "pyproject.toml"
        if not pyproject.exists():
            return 1
        return self._pyproject_package_name_line(pyproject, self._package_name(repo)) or 1

    def _package_name(self, repo: RepoSnapshot) -> str:
        pyproject = repo.root / "pyproject.toml"
        if not pyproject.exists():
            return repo.name
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return repo.name
        project = data.get("project")
        if isinstance(project, dict) and project.get("name"):
            return str(project["name"])
        tool = data.get("tool")
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        if isinstance(poetry, dict) and poetry.get("name"):
            return str(poetry["name"])
        return repo.name

    def _pyproject_package_name_line(self, pyproject: Path, package_name: str) -> int | None:
        try:
            lines = pyproject.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        current_table = ""
        for line_number, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if stripped.startswith("["):
                current_table = self._toml_table_header_name(stripped) or ""
                continue
            key, separator, raw_value = stripped.partition("=")
            if separator != "=" or key.strip() != "name":
                continue
            if current_table not in {"project", "tool.poetry"}:
                continue
            try:
                parsed = tomllib.loads(f"name = {raw_value.strip()}\n")
            except tomllib.TOMLDecodeError:
                continue
            if parsed.get("name") == package_name:
                return line_number
        return None

    def _toml_table_header_name(self, line: str) -> str | None:
        try:
            parsed = tomllib.loads(f"{line}\n")
        except tomllib.TOMLDecodeError:
            return None
        current: object = parsed
        parts = []
        while isinstance(current, dict) and len(current) == 1:
            key, value = next(iter(current.items()))
            parts.append(str(key))
            current = value
        if current == {} and parts:
            return ".".join(parts)
        return None

    def _module_name(self, repo: RepoSnapshot, file_path: Path) -> str:
        relative = file_path.relative_to(repo.root).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        return ".".join(parts) or repo.name

    def _call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = self._call_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    def _call_root(self, node: ast.AST) -> str | None:
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        return current.id if isinstance(current, ast.Name) else None

    def _can_bind_call_by_short_name(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return True
        return isinstance(node, ast.Attribute) and self._call_root(node) in {"self", "cls"}

    def _qualname_for_node(self, tree: ast.AST, target: ast.AST) -> str:
        path: list[str] = []

        def visit(node: ast.AST, parents: list[str]) -> bool:
            if node is target:
                path.extend(parents + [getattr(node, "name", "")])
                return True
            child_parents = parents
            if isinstance(node, ast.ClassDef):
                child_parents = parents + [node.name]
            for child in ast.iter_child_nodes(node):
                if visit(child, child_parents):
                    return True
            return False

        visit(tree, [])
        return ".".join(part for part in path if part)
