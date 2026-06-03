from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.dotnet.extractors.csharp_extractor import CSharpExtractor


@dataclass(frozen=True)
class ExtractorAdapter:
    capability: AdapterCapability
    extractor: CSharpExtractor

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("dotnet", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = self.extractor.extract_with_context(repo, ctx)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


DOTNET_CSHARP_BRIDGE_ADAPTER = ExtractorAdapter(
    capability=AdapterCapability(
        name="dotnet-csharp-bridge",
        languages=("dotnet",),
        file_kinds=("dotnet",),
        framework_tags=("MassTransit",),
        produces_predicates=("DEFINED_IN", "IMPLEMENTS", "IMPORTS", "CALLS", "CONSUMES_EVENT", "PRODUCES_EVENT"),
        produces_entity_kinds=("Repo", "Service", "CodeModule", "CodeSymbol", "ExternalPackage", "EventChannel"),
        ontology_scope="mixed",
        source_system=CSharpExtractor.source_system,
    ),
    extractor=CSharpExtractor(),
)
