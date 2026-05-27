from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.file_formats._shared.static_config import StaticConfigExtractor


@dataclass(frozen=True)
class ExtractorAdapter:
    capability: AdapterCapability
    extractor: StaticConfigExtractor

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = self.extractor.extract(repo, files=scannable_config_files(repo, ctx), tenant_id=ctx.tenant_id)
        build.coverage.extend(scan_coverage_rows(repo, ctx))
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


STATIC_CONFIG_ADAPTER = ExtractorAdapter(
    capability=AdapterCapability(
        name="static-config",
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
    extractor=StaticConfigExtractor(
        include_static_site_cname=False,
        include_domain_env=False,
        include_openapi=False,
        include_deploy_events=False,
    ),
)
