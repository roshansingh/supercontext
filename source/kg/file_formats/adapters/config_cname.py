from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.static_config import StaticConfigExtractor, service_entity_for_repo
from source.kg.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.file_formats.cname import extract_cname_domains


@dataclass(frozen=True)
class ConfigCnameAdapter:
    capability = AdapterCapability(
        name="config-cname",
        languages=("config",),
        file_kinds=("config",),
        framework_tags=("cname", "static-site"),
        produces_predicates=("REFERENCES_DOMAIN",),
        produces_entity_kinds=("Domain",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return any(scanned.path.name == "CNAME" for scanned in scannable_config_files(repo, ctx))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = service_entity_for_repo(repo, ctx.tenant_id)
        cname_files = [scanned for scanned in scannable_config_files(repo, ctx) if scanned.path.name == "CNAME"]
        extract_cname_domains(repo, cname_files, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_CNAME_ADAPTER = ConfigCnameAdapter()
