from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.languages.dotnet.extractors.dotnet_events import extract_dotnet_events
from source.kg.languages.dotnet.extractors.parser_bridge import parse_dotnet_repo


@dataclass
class KgBuild:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


class CSharpExtractor:
    source_system = "dotnet_csharp_bridge_v0"

    def extract(self, repo: RepoSnapshot) -> KgBuild:
        return self.extract_with_context(repo, None)

    def extract_with_context(self, repo: RepoSnapshot, ctx: ExtractionContext | None) -> KgBuild:
        tenant_id = ctx.tenant_id if ctx is not None else resolve_tenant_id()
        build = KgBuild()

        repo_entity = self._repo_entity(repo, tenant_id)
        service_entity = self._service_entity(repo, tenant_id)
        build.entities.extend([repo_entity, service_entity])
        build.evidence.append(self._repo_evidence(repo, repo_entity))
        build.evidence.append(self._service_evidence(repo, service_entity))
        self._add_fact(
            build,
            predicate="DEFINED_IN",
            subject=service_entity,
            object_=repo_entity,
            repo=repo,
            file_path=repo.root,
            line_start=1,
            line_end=1,
        )

        parsed_files = parse_dotnet_repo(repo, ctx)
        for file_path in repo.files_by_language.get("dotnet", ()):
            if file_path.suffix != ".cs":
                continue
            parsed_file = parsed_files.get(str(file_path.relative_to(repo.root)), {})
            self._extract_file(repo, file_path, repo_entity, service_entity, parsed_file, build, ctx, tenant_id)
            for diagnostic in parsed_file.get("parse_diagnostics", []):
                build.coverage.append(
                    Coverage(
                        tenant_id=tenant_id,
                        predicate="PARSES",
                        scope_ref={
                            "repo": repo.name,
                            "language": "dotnet/csharp",
                            "path": str(file_path.relative_to(repo.root)),
                            "line": diagnostic.get("line", 1),
                            "message": diagnostic.get("message", "parse diagnostic"),
                            "reason": "parse_error",
                        },
                        state="uninstrumented",
                        source_system=self.source_system,
                    )
                )

        build.coverage.append(
            Coverage(
                tenant_id=tenant_id,
                predicate="PARSES",
                scope_ref={"repo": repo.name, "language": "dotnet/csharp", "path_prefix": "."},
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
        parsed_file: JsonObject,
        build: KgBuild,
        ctx: ExtractionContext | None,
        tenant_id: str,
    ) -> None:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        line_count = max(1, len(source.splitlines()))
        module_name = self._module_name(repo, file_path)

        module_entity = Entity(
            kind="CodeModule",
            identity={"tenant_id": tenant_id, "repo": repo.name, "module": module_name},
            properties={"path": str(file_path.relative_to(repo.root)), "language": "dotnet/csharp"},
        )
        build.entities.append(module_entity)
        build.evidence.append(self._entity_evidence(repo, module_entity, file_path, 1, line_count))
        self._add_fact(build, "DEFINED_IN", module_entity, repo_entity, repo, file_path, 1, 1)
        self._add_fact(build, "IMPLEMENTS", module_entity, service_entity, repo, file_path, 1, 1)

        imports = parsed_file.get("imports", [])
        if ctx is not None:
            for imp in imports:
                raw_target = str(imp.get("raw_target", ""))
                if raw_target:
                    ctx.import_roots_by_language.setdefault("dotnet", set()).add(raw_target)

        for imp in imports:
            raw_target = str(imp.get("raw_target", ""))
            if not raw_target:
                continue
            line = int(imp.get("line") or 1)
            external_entity = Entity(
                kind="ExternalPackage",
                identity={"tenant_id": tenant_id, "repo": repo.name, "name": raw_target},
                properties={"import_root": raw_target, "category": "unknown"},
            )
            build.entities.append(external_entity)
            build.evidence.append(self._entity_evidence(repo, external_entity, file_path, line, line))
            self._add_fact(
                build,
                "IMPORTS",
                module_entity,
                external_entity,
                repo,
                file_path,
                line,
                line,
                qualifier={
                    "raw_import": raw_target,
                    "import_root": raw_target,
                    "category": "unknown",
                },
            )

        symbols_by_key: dict[str, Entity] = {}
        symbol_keys_by_id: dict[str, str] = {}
        symbols_by_qualname: dict[str, list[Entity]] = {}
        symbols_by_short: dict[str, list[Entity]] = {}
        symbol_arities: dict[str, int] = {}
        for sym in parsed_file.get("symbols", []):
            qualname = str(sym.get("name", "")).strip()
            if not qualname:
                continue
            kind = str(sym.get("kind", "symbol"))
            symbol_key = str(sym.get("key") or qualname).strip()
            signature = str(sym.get("signature") or "").strip()
            line = int(sym.get("line") or 1)
            end_line = int(sym.get("end_line") or line)
            identity: JsonObject = {
                "tenant_id": tenant_id,
                "repo": repo.name,
                "module": module_name,
                "qualname": qualname,
                "symbol_kind": kind,
            }
            if signature:
                identity["signature"] = signature
            symbol_entity = Entity(
                kind="CodeSymbol",
                identity=identity,
                properties={
                    "path": str(file_path.relative_to(repo.root)),
                    "line": line,
                    "end_line": end_line,
                    "language": "dotnet/csharp",
                },
            )
            build.entities.append(symbol_entity)
            build.evidence.append(self._entity_evidence(repo, symbol_entity, file_path, line, end_line))
            self._add_fact(build, "DEFINED_IN", symbol_entity, module_entity, repo, file_path, line, line)
            symbols_by_key[symbol_key] = symbol_entity
            symbol_keys_by_id[symbol_entity.entity_id] = symbol_key
            symbols_by_qualname.setdefault(qualname, []).append(symbol_entity)
            short = qualname.rsplit(".", 1)[-1]
            symbols_by_short.setdefault(short, []).append(symbol_entity)
            arity = sym.get("arity")
            if isinstance(arity, int) and not isinstance(arity, bool):
                symbol_arities[symbol_entity.entity_id] = arity

        for call in parsed_file.get("calls", []):
            caller_qualname = str(call.get("caller", "")).strip()
            caller_key = str(call.get("caller_key") or "").strip()
            callee_name = str(call.get("name", "")).strip()
            if not caller_qualname or not callee_name:
                continue
            caller = symbols_by_key.get(caller_key) if caller_key else None
            if caller is None:
                caller_candidates = symbols_by_qualname.get(caller_qualname, [])
                if len(caller_candidates) != 1:
                    continue
                caller = caller_candidates[0]
            if caller is None:
                continue
            short_callee = callee_name.rsplit(".", 1)[-1]
            callees = symbols_by_short.get(short_callee, [])
            arity = call.get("arity")
            if isinstance(arity, int) and not isinstance(arity, bool):
                callees = [
                    callee
                    for callee in callees
                    if symbol_arities.get(callee.entity_id) == arity
                ]
            if len(callees) != 1 and caller_key:
                scoped_callees = self._scope_candidate_callees(caller_key, short_callee, callees, symbol_keys_by_id, arity)
                if scoped_callees:
                    callees = scoped_callees
            if len(callees) != 1:
                continue
            callee = callees[0]
            if callee.entity_id == caller.entity_id:
                continue
            line = int(call.get("line") or 1)
            self._add_fact(
                build,
                "CALLS",
                caller,
                callee,
                repo,
                file_path,
                line,
                line,
                qualifier={"call": callee_name},
            )

        extract_dotnet_events(
            repo=repo,
            file_path=file_path,
            parsed_file=parsed_file,
            symbols_by_qualname=symbols_by_qualname,
            symbols_by_key=symbols_by_key,
            build=build,
            tenant_id=tenant_id,
            source_system=self.source_system,
            add_fact=self._add_fact,
            entity_evidence=self._entity_evidence,
        )

    def _scope_candidate_callees(
        self,
        caller_key: str,
        short_callee: str,
        callees: list[Entity],
        symbol_keys_by_id: dict[str, str],
        arity: object,
    ) -> list[Entity]:
        parent_scope = caller_key.rsplit(".", 1)[0] if "." in caller_key else ""
        if not parent_scope:
            return []
        if isinstance(arity, int) and not isinstance(arity, bool):
            expected_key = f"{parent_scope}.{short_callee}/{arity}"
        else:
            expected_key = f"{parent_scope}.{short_callee}"
        return [
            callee
            for callee in callees
            if symbol_keys_by_id.get(callee.entity_id) == expected_key
        ]

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
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="git",
            source_ref={
                "repo_path": str(repo.root),
                "commit_sha": repo.commit_sha,
                "service_slug": self._service_slug(repo),
            },
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
        path = "." if file_path == repo.root else str(file_path.relative_to(repo.root))
        return {
            "repo": repo.name,
            "commit_sha": repo.commit_sha,
            "path": path,
            "line_start": line_start,
            "line_end": line_end,
        }

    def _module_name(self, repo: RepoSnapshot, file_path: Path) -> str:
        relative = file_path.relative_to(repo.root).with_suffix("")
        parts = [part for part in relative.parts if part]
        return ".".join(parts) or repo.name

    def _service_slug(self, repo: RepoSnapshot) -> str:
        return re.sub(r"[^a-z0-9]+", "-", repo.name.lower()).strip("-") or repo.name
