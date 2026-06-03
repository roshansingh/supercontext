from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.endpoints import extract_dotnet_endpoints
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.languages.dotnet.extractors.parser_bridge import parse_dotnet_repo


@dataclass(frozen=True)
class DotnetEndpointsAdapter:
    capability = AdapterCapability(
        name="dotnet-endpoints",
        languages=("dotnet",),
        file_kinds=("dotnet",),
        framework_tags=("Microsoft.AspNetCore.Mvc",),
        produces_predicates=("EXPOSES_ENDPOINT",),
        produces_entity_kinds=("Endpoint",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("dotnet", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        parsed_files = parse_dotnet_repo(repo, ctx)
        extract_dotnet_endpoints(repo, parsed_files, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


DOTNET_ENDPOINTS_ADAPTER = DotnetEndpointsAdapter()
