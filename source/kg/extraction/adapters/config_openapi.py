from __future__ import annotations

from dataclasses import dataclass

from source.kg.extraction.adapters.config_shared import scannable_config_files
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ConfigKgBuild
from source.kg.extraction.config.endpoints import extract_openapi_document
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
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
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        for scanned in scannable_config_files(repo, ctx):
            extract_openapi_document(repo, scanned, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


CONFIG_OPENAPI_ADAPTER = ConfigOpenApiAdapter()
