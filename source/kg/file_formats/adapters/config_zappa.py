from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.file_formats.zappa import extract_zappa_event_sources
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigZappaAdapter:
    capability = AdapterCapability(
        name="config-zappa",
        languages=("config",),
        file_kinds=("json",),
        framework_tags=("zappa",),
        produces_predicates=("CONSUMES_EVENT", "DEPLOYS_VIA_CONFIG", "REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"),
        produces_entity_kinds=("EventChannel", "DeployTarget", "Domain"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        for scanned in scannable_config_files(repo, ctx):
            if scanned.path.name == "zappa_settings.json":
                extract_zappa_event_sources(repo, scanned, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_ZAPPA_ADAPTER = ConfigZappaAdapter()
