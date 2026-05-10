from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.extraction.python.ast_extractor import PythonAstExtractor
from source.kg.extraction.typescript.compiler_api_extractor import TypeScriptCompilerApiExtractor


class LegacyExtractor(Protocol):
    def extract(self, repo: RepoSnapshot) -> Any: ...


@dataclass(frozen=True)
class LegacyAdapter:
    capability: AdapterCapability
    extractor: LegacyExtractor
    language_gate: str | None = None

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        if self.language_gate == "python":
            return bool(repo.python_files)
        if self.language_gate == "typescript":
            return bool(repo.typescript_files)
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = self.extractor.extract(repo)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


LEGACY_STATIC_CONFIG_ADAPTER = LegacyAdapter(
    capability=AdapterCapability(
        name="legacy-static-config",
        languages=("config",),
        file_kinds=("config",),
        framework_tags=(),
        produces_predicates=(
            "DEFINED_IN",
            "EXPOSES_ENDPOINT",
            "CALLS_ENDPOINT",
        ),
        produces_entity_kinds=("Repo", "Service", "Endpoint"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    ),
    extractor=StaticConfigExtractor(include_domain_env=False, include_openapi=False, include_deploy_events=False),
)

LEGACY_PYTHON_AST_ADAPTER = LegacyAdapter(
    capability=AdapterCapability(
        name="legacy-python-ast",
        languages=("python",),
        file_kinds=("python",),
        framework_tags=("flask", "django", "fastapi"),
        produces_predicates=(
            "DEFINED_IN",
            "IMPLEMENTS",
            "IMPORTS",
            "CALLS",
            "EXPOSES_ENDPOINT",
        ),
        produces_entity_kinds=(
            "Repo",
            "Service",
            "CodeModule",
            "CodeSymbol",
            "ExternalPackage",
            "Endpoint",
        ),
        ontology_scope="mixed",
        source_system=PythonAstExtractor.source_system,
    ),
    extractor=PythonAstExtractor(include_transport=False),
    language_gate="python",
)

LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER = LegacyAdapter(
    capability=AdapterCapability(
        name="legacy-typescript-compiler-api",
        languages=("javascript", "typescript"),
        file_kinds=("javascript", "typescript"),
        framework_tags=(),
        produces_predicates=("DEFINED_IN", "IMPLEMENTS", "IMPORTS", "CALLS"),
        produces_entity_kinds=("Repo", "Service", "CodeModule", "CodeSymbol", "ExternalPackage"),
        ontology_scope="mixed",
        source_system=TypeScriptCompilerApiExtractor.source_system,
    ),
    extractor=TypeScriptCompilerApiExtractor(),
    language_gate="typescript",
)
