from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import re

from source.kg.js_import_normalizer import JsImportNormalizer, JsImportRef, NormalizedJsImport
from source.kg.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.repo_source import RepoSnapshot


TENANT_ID = "local-dev"

IMPORT_FROM_RE = re.compile(r"^\s*import\s+(type\s+)?(.+?)\s+from\s+['\"]([^'\"]+)['\"]")
SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]")
REQUIRE_RE = re.compile(r"^\s*(?:const|let|var)\s+(.+?)\s*=\s*require\(['\"]([^'\"]+)['\"]\)")
FUNCTION_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")
TYPE_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(class|interface|type|enum)\s+([A-Za-z_$][\w$]*)")
VALUE_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]")
CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")

CALL_KEYWORDS = {
    "catch",
    "describe",
    "for",
    "function",
    "if",
    "it",
    "return",
    "switch",
    "test",
    "while",
}


@dataclass
class KgBuild:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolDef:
    entity: Entity
    qualname: str
    symbol_kind: str
    line: int


class TypeScriptStaticExtractor:
    source_system = "typescript_static_v0"

    def extract(self, repo: RepoSnapshot) -> KgBuild:
        build = KgBuild()
        repo_entity = self._repo_entity(repo)
        service_entity = self._service_entity(repo)
        build.entities.extend([repo_entity, service_entity])
        build.evidence.extend([self._repo_evidence(repo, repo_entity), self._service_evidence(repo, service_entity)])
        self._add_fact(build, "DEFINED_IN", service_entity, repo_entity, repo, self._package_json(repo), 1, 1)

        normalizer = JsImportNormalizer(repo)
        for file_path in repo.typescript_files:
            self._extract_file(repo, file_path, repo_entity, service_entity, normalizer, build)

        build.coverage.append(
            Coverage(
                tenant_id=TENANT_ID,
                predicate="IMPORTS",
                scope_ref={"repo": repo.name, "language": "typescript/javascript", "path_prefix": "."},
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
        normalizer: JsImportNormalizer,
        build: KgBuild,
    ) -> None:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        module_name = self._module_name(repo, file_path)
        module_entity = Entity(
            kind="CodeModule",
            identity={"tenant_id": TENANT_ID, "repo": repo.name, "module": module_name},
            properties={"path": str(file_path.relative_to(repo.root)), "language": self._language(file_path)},
        )
        build.entities.append(module_entity)
        build.evidence.append(self._entity_evidence(repo, module_entity, file_path, 1, max(1, len(lines))))
        self._add_fact(build, "DEFINED_IN", module_entity, repo_entity, repo, file_path, 1, 1)
        self._add_fact(build, "IMPLEMENTS", module_entity, service_entity, repo, file_path, 1, 1)

        imports = [normalizer.normalize(ref, module_name) for ref in self._collect_imports(lines)]
        imports_by_local = self._imports_by_local(imports)
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

        symbols = self._collect_symbols(repo, file_path, module_name, lines)
        symbols_by_short_name = {symbol.qualname.rsplit(".", 1)[-1]: symbol for symbol in symbols}
        for symbol in symbols:
            build.entities.append(symbol.entity)
            build.evidence.append(self._entity_evidence(repo, symbol.entity, file_path, symbol.line, symbol.line))
            self._add_fact(build, "DEFINED_IN", symbol.entity, module_entity, repo, file_path, symbol.line, symbol.line)

        symbol_ranges = self._symbol_ranges(symbols, len(lines))
        for symbol, start, end in symbol_ranges:
            for line_number in range(start, end + 1):
                line = lines[line_number - 1]
                for call_name in self._call_names(line):
                    short_name = call_name.rsplit(".", 1)[-1]
                    if short_name in symbols_by_short_name and symbols_by_short_name[short_name] != symbol:
                        self._add_fact(
                            build,
                            "CALLS",
                            symbol.entity,
                            symbols_by_short_name[short_name].entity,
                            repo,
                            file_path,
                            line_number,
                            line_number,
                        )
                        continue
                    root = call_name.split(".", 1)[0]
                    import_ref = imports_by_local.get(root)
                    if import_ref:
                        self._add_fact(
                            build,
                            "CALLS",
                            symbol.entity,
                            self._dependency_entity(repo, import_ref),
                            repo,
                            file_path,
                            line_number,
                            line_number,
                            qualifier={"call": call_name},
                        )

    def _collect_imports(self, lines: list[str]) -> list[JsImportRef]:
        refs: list[JsImportRef] = []
        for index, line in enumerate(lines, start=1):
            from_match = IMPORT_FROM_RE.match(line)
            if from_match:
                is_type_only = bool(from_match.group(1))
                clause = from_match.group(2).strip()
                target = from_match.group(3)
                imported_names, local_names = self._parse_import_clause(clause)
                refs.append(
                    JsImportRef(
                        raw_target=target,
                        line=index,
                        imported_names=tuple(imported_names),
                        local_names=tuple(local_names),
                        is_type_only=is_type_only,
                    )
                )
                continue
            side_effect_match = SIDE_EFFECT_IMPORT_RE.match(line)
            if side_effect_match:
                refs.append(JsImportRef(raw_target=side_effect_match.group(1), line=index, imported_names=(), local_names=()))
                continue
            require_match = REQUIRE_RE.match(line)
            if require_match:
                local_names = tuple(self._names_from_binding(require_match.group(1)))
                refs.append(
                    JsImportRef(
                        raw_target=require_match.group(2),
                        line=index,
                        imported_names=local_names,
                        local_names=local_names,
                    )
                )
        return refs

    def _parse_import_clause(self, clause: str) -> tuple[list[str], list[str]]:
        clause = clause.removeprefix("type ").strip()
        imported_names: list[str] = []
        local_names: list[str] = []
        namespace_match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", clause)
        if namespace_match:
            return [namespace_match.group(1)], [namespace_match.group(1)]

        named_match = re.search(r"\{(.+?)\}", clause)
        if named_match:
            for name in named_match.group(1).split(","):
                name = name.strip().removeprefix("type ").strip()
                if not name:
                    continue
                parts = [part.strip() for part in name.split(" as ", 1)]
                imported_names.append(parts[0])
                local_names.append(parts[-1])

        default_part = clause.split("{", 1)[0].strip().strip(",")
        if default_part and re.match(r"^[A-Za-z_$][\w$]*$", default_part):
            imported_names.append("default")
            local_names.append(default_part)
        return imported_names, local_names

    def _names_from_binding(self, binding: str) -> list[str]:
        return re.findall(r"[A-Za-z_$][\w$]*", binding)

    def _collect_symbols(self, repo: RepoSnapshot, file_path: Path, module_name: str, lines: list[str]) -> list[SymbolDef]:
        symbols: list[SymbolDef] = []
        brace_depth = 0
        for index, line in enumerate(lines, start=1):
            if brace_depth == 0:
                match = FUNCTION_RE.match(line)
                if match:
                    symbols.append(self._symbol(repo, file_path, module_name, match.group(1), "function", index))
                else:
                    match = TYPE_RE.match(line)
                    if match:
                        symbols.append(self._symbol(repo, file_path, module_name, match.group(2), match.group(1), index))
                    else:
                        match = VALUE_RE.match(line)
                        if match:
                            kind = "function" if "=>" in line else "value"
                            symbols.append(self._symbol(repo, file_path, module_name, match.group(1), kind, index))
            brace_depth = max(0, brace_depth + line.count("{") - line.count("}"))
        return symbols

    def _symbol(self, repo: RepoSnapshot, file_path: Path, module_name: str, name: str, kind: str, line: int) -> SymbolDef:
        entity = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": TENANT_ID,
                "repo": repo.name,
                "module": module_name,
                "qualname": name,
                "symbol_kind": kind,
            },
            properties={"path": str(file_path.relative_to(repo.root)), "line": line, "language": self._language(file_path)},
        )
        return SymbolDef(entity=entity, qualname=name, symbol_kind=kind, line=line)

    def _symbol_ranges(self, symbols: list[SymbolDef], line_count: int) -> list[tuple[SymbolDef, int, int]]:
        sorted_symbols = sorted(symbols, key=lambda symbol: symbol.line)
        ranges: list[tuple[SymbolDef, int, int]] = []
        for index, symbol in enumerate(sorted_symbols):
            end = sorted_symbols[index + 1].line - 1 if index + 1 < len(sorted_symbols) else line_count
            ranges.append((symbol, symbol.line, max(symbol.line, end)))
        return ranges

    def _call_names(self, line: str) -> list[str]:
        names: list[str] = []
        for match in CALL_RE.finditer(line):
            call_name = match.group(1)
            if call_name in CALL_KEYWORDS or call_name.startswith("."):
                continue
            names.append(call_name)
        return names

    def _imports_by_local(self, imports: list[NormalizedJsImport]) -> dict[str, NormalizedJsImport]:
        by_local: dict[str, NormalizedJsImport] = {}
        for import_ref in imports:
            for local_name in import_ref.local_names:
                by_local.setdefault(local_name, import_ref)
        return by_local

    def _dependency_entity(self, repo: RepoSnapshot, import_ref: NormalizedJsImport) -> Entity:
        if import_ref.category in {"internal_module", "relative_internal_module"}:
            return Entity(
                kind="CodeModule",
                identity={"tenant_id": TENANT_ID, "repo": repo.name, "module": import_ref.target_name},
                properties={"dependency_category": import_ref.category},
            )
        return Entity(
            kind="ExternalPackage",
            identity={"tenant_id": TENANT_ID, "repo": repo.name, "name": import_ref.target_name},
            properties={
                "category": import_ref.category,
                "import_root": import_ref.import_root,
                "distribution_name": import_ref.distribution_name,
            },
        )

    def _import_qualifier(self, import_ref: NormalizedJsImport) -> JsonObject:
        return {
            "raw_import": import_ref.raw_import,
            "import_root": import_ref.import_root,
            "distribution_name": import_ref.distribution_name,
            "category": import_ref.category,
            "module_name": import_ref.module_name,
            "imported_names": list(import_ref.imported_names),
            "local_names": list(import_ref.local_names),
            "is_type_only": import_ref.is_type_only,
        }

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
        package_json = self._package_json(repo)
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="package_json",
            source_ref={"package_name": self._package_name(repo)},
            bytes_ref=self._bytes_ref(repo, package_json, 1, 1) if package_json.exists() else None,
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

    def _module_name(self, repo: RepoSnapshot, file_path: Path) -> str:
        relative = file_path.relative_to(repo.root).with_suffix("")
        parts = [part for part in relative.parts if part != "index"]
        return ".".join(parts) or repo.name

    def _language(self, file_path: Path) -> str:
        if file_path.suffix in {".ts", ".tsx", ".mts", ".cts"}:
            return "typescript"
        return "javascript"

    def _package_json(self, repo: RepoSnapshot) -> Path:
        return repo.root / "package.json"

    def _package_name(self, repo: RepoSnapshot) -> str:
        package_json = self._package_json(repo)
        if not package_json.exists():
            return repo.name
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return repo.name
        return str(data.get("name") or repo.name)

    def _service_slug(self, repo: RepoSnapshot) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self._package_name(repo).lower()).strip("-") or repo.name
