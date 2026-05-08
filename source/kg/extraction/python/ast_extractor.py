from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib
import warnings

from source.kg.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.normalization.python.imports import NormalizedImport, PythonImportNormalizer
from source.kg.repo_source import RepoSnapshot


TENANT_ID = "local-dev"


@dataclass
class KgBuild:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
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


class PythonAstExtractor:
    source_system = "python_ast_v0"

    def extract(self, repo: RepoSnapshot) -> KgBuild:
        build = KgBuild()
        repo_entity = self._repo_entity(repo)
        service_entity = self._service_entity(repo)
        build.entities.extend([repo_entity, service_entity])
        build.evidence.extend(
            [
                self._repo_evidence(repo, repo_entity),
                self._service_evidence(repo, service_entity),
            ]
        )
        self._add_fact(build, "DEFINED_IN", service_entity, repo_entity, repo, repo.root / "pyproject.toml", 1, 1)
        import_normalizer = PythonImportNormalizer(repo)

        for file_path in repo.python_files:
            self._extract_file(repo, file_path, repo_entity, service_entity, import_normalizer, build)

        build.coverage.append(
            Coverage(
                tenant_id=TENANT_ID,
                predicate="CALLS",
                scope_ref={"repo": repo.name, "language": "python", "path_prefix": "."},
                state="instrumented",
                source_system=self.source_system,
            )
        )
        return build

    def _extract_file(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        repo_entity: Entity,
        service_entity: Entity,
        import_normalizer: PythonImportNormalizer,
        build: KgBuild,
    ) -> None:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            build.coverage.append(
                Coverage(
                    tenant_id=TENANT_ID,
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
                        "message": str(exc),
                    },
                    bytes_ref=self._bytes_ref(repo, file_path, getattr(exc, "lineno", 1) or 1, getattr(exc, "lineno", 1) or 1),
                    confidence=1.0,
                )
            )
            return
        module_name = self._module_name(repo, file_path)
        module_entity = Entity(
            kind="CodeModule",
            identity={"tenant_id": TENANT_ID, "repo": repo.name, "module": module_name},
            properties={"path": str(file_path.relative_to(repo.root))},
        )
        build.entities.append(module_entity)
        build.evidence.append(self._entity_evidence(repo, module_entity, file_path, 1, max(1, len(source.splitlines()))))
        self._add_fact(build, "DEFINED_IN", module_entity, repo_entity, repo, file_path, 1, 1)
        self._add_fact(build, "IMPLEMENTS", module_entity, service_entity, repo, file_path, 1, 1)

        symbols = self._collect_symbols(repo, file_path, module_name, tree)
        by_qualname = {symbol.qualname: symbol for symbol in symbols}
        by_short_name = {symbol.qualname.rsplit(".", 1)[-1]: symbol for symbol in symbols}
        for symbol in symbols:
            build.entities.append(symbol.entity)
            build.evidence.append(self._entity_evidence(repo, symbol.entity, file_path, symbol.line, symbol.end_line))
            self._add_fact(build, "DEFINED_IN", symbol.entity, module_entity, repo, file_path, symbol.line, symbol.end_line)

        imports = import_normalizer.collect(tree, module_name)
        imports_by_root: dict[str, NormalizedImport] = {}
        for import_ref in imports:
            dependency_entity = self._dependency_entity(repo, import_ref)
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

        for caller_node in ast.walk(tree):
            if not isinstance(caller_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller_name = self._qualname_for_node(tree, caller_node)
            caller = by_qualname.get(caller_name)
            if caller is None:
                continue
            for call_node in [node for node in ast.walk(caller_node) if isinstance(node, ast.Call)]:
                call_name = self._call_name(call_node.func)
                if not call_name:
                    continue
                line = getattr(call_node, "lineno", caller.line)
                local_callee = by_short_name.get(call_name.split(".")[-1])
                if local_callee is not None and local_callee.entity.entity_id != caller.entity.entity_id:
                    self._add_fact(build, "CALLS", caller.entity, local_callee.entity, repo, file_path, line, line)
                    continue
                root = call_name.split(".", 1)[0]
                if root in imports_by_root:
                    package_entity = self._dependency_entity(repo, imports_by_root[root])
                    build.entities.append(package_entity)
                    self._add_fact(
                        build,
                        "CALLS",
                        caller.entity,
                        package_entity,
                        repo,
                        file_path,
                        line,
                        line,
                        qualifier={"call": call_name},
                    )

    def _collect_symbols(self, repo: RepoSnapshot, file_path: Path, module_name: str, tree: ast.AST) -> list[SymbolDef]:
        symbols: list[SymbolDef] = []

        def visit(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    symbols.append(self._symbol(repo, file_path, module_name, qualname, "class", node))
                    visit(node.body, qualname)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                    if prefix:
                        kind = "method"
                    symbols.append(self._symbol(repo, file_path, module_name, qualname, kind, node))

        if isinstance(tree, ast.Module):
            visit(tree.body)
        return symbols

    def _symbol(
        self,
        repo: RepoSnapshot,
        file_path: Path,
        module_name: str,
        qualname: str,
        symbol_kind: str,
        node: ast.AST,
    ) -> SymbolDef:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)
        entity = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": TENANT_ID,
                "repo": repo.name,
                "module": module_name,
                "qualname": qualname,
                "symbol_kind": symbol_kind,
            },
            properties={"path": str(file_path.relative_to(repo.root)), "line": line},
        )
        return SymbolDef(entity, module_name, qualname, symbol_kind, line, end_line)

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
    ) -> None:
        fact = Fact(predicate=predicate, subject_id=subject.entity_id, object_id=object_.entity_id, qualifier=qualifier or {})
        build.facts.append(fact)
        build.evidence.append(
            Evidence(
                target_type="fact",
                target_id=fact.fact_id,
                derivation_class="deterministic_static",
                source_system=self.source_system,
                source_ref={"extractor": self.source_system, "predicate": predicate},
                bytes_ref=self._bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    def _repo_entity(self, repo: RepoSnapshot) -> Entity:
        return Entity(
            kind="Repo",
            identity={"tenant_id": TENANT_ID, "host": "local", "owner": repo.owner, "name": repo.name},
            properties={"path": str(repo.root), "commit_sha": repo.commit_sha},
        )

    def _service_entity(self, repo: RepoSnapshot) -> Entity:
        return Entity(
            kind="Service",
            identity={"tenant_id": TENANT_ID, "namespace": "default", "slug": self._service_slug(repo)},
            properties={"repo": repo.name},
        )

    def _dependency_entity(self, repo: RepoSnapshot, import_ref: NormalizedImport) -> Entity:
        if import_ref.category in {"internal_module", "relative_internal_module"}:
            return Entity(
                kind="CodeModule",
                identity={"tenant_id": TENANT_ID, "repo": repo.name, "module": import_ref.target_name},
                properties={"dependency_category": import_ref.category},
            )
        return self._external_package(repo, import_ref)

    def _external_package(self, repo: RepoSnapshot, import_ref: NormalizedImport) -> Entity:
        return Entity(
            kind="ExternalPackage",
            identity={"tenant_id": TENANT_ID, "repo": repo.name, "name": import_ref.target_name},
            properties={
                "category": import_ref.category,
                "import_root": import_ref.import_root,
                "distribution_name": import_ref.distribution_name,
            },
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

    def _service_evidence(self, repo: RepoSnapshot, entity: Entity) -> Evidence:
        pyproject = repo.root / "pyproject.toml"
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="pyproject",
            source_ref={"package_name": self._package_name(repo)},
            bytes_ref=self._bytes_ref(repo, pyproject, 1, 1) if pyproject.exists() else None,
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

    def _package_name(self, repo: RepoSnapshot) -> str:
        pyproject = repo.root / "pyproject.toml"
        if not pyproject.exists():
            return repo.name
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return repo.name
        return str(data.get("tool", {}).get("poetry", {}).get("name") or repo.name)

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
