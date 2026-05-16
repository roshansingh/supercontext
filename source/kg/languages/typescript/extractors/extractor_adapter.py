from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.typescript.extractors.compiler_api_extractor import TypeScriptCompilerApiExtractor


@dataclass(frozen=True)
class ExtractorAdapter:
    capability: AdapterCapability
    extractor: TypeScriptCompilerApiExtractor

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("typescript", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = self.extractor.extract_with_context(repo, ctx)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


TYPESCRIPT_COMPILER_API_ADAPTER = ExtractorAdapter(
    capability=AdapterCapability(
        name="typescript-compiler-api",
        languages=("javascript", "typescript"),
        file_kinds=("javascript", "typescript"),
        framework_tags=(),
        produces_predicates=("DEFINED_IN", "IMPLEMENTS", "IMPORTS", "CALLS"),
        produces_entity_kinds=("Repo", "Service", "CodeModule", "CodeSymbol", "ExternalPackage"),
        ontology_scope="mixed",
        source_system=TypeScriptCompilerApiExtractor.source_system,
    ),
    extractor=TypeScriptCompilerApiExtractor(),
)
