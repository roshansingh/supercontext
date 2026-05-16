from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats.serverless_yaml import extract_serverless_yaml_routes
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigServerlessYamlAdapter:
    capability = AdapterCapability(
        name="config-serverless-yaml",
        languages=("config",),
        file_kinds=("yaml", "yml"),
        framework_tags=("serverless",),
        produces_predicates=("EXPOSES_ENDPOINT", "CONSUMES_EVENT"),
        produces_entity_kinds=("Endpoint", "EventChannel"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        for scanned in scannable_config_files(repo, ctx):
            extract_serverless_yaml_routes(repo, scanned, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_SERVERLESS_YAML_ADAPTER = ConfigServerlessYamlAdapter()
