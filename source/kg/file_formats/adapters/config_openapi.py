from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.endpoints import extract_openapi_document
from source.kg.file_formats._shared.static_config import StaticConfigExtractor, service_entity_for_repo
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigOpenApiAdapter:
    capability = AdapterCapability(
        name="config-openapi",
        languages=("config",),
        file_kinds=("json", "yaml", "yml"),
        framework_tags=("openapi", "swagger"),
        produces_predicates=("DOCUMENTS_ENDPOINT",),
        produces_entity_kinds=("Endpoint",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = service_entity_for_repo(repo, ctx.tenant_id)
        for scanned in scannable_config_files(repo, ctx):
            extract_openapi_document(repo, scanned, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_OPENAPI_ADAPTER = ConfigOpenApiAdapter()
