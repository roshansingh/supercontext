from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.file_formats.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.extraction.file_formats.common import ConfigKgBuild
from source.kg.extraction.file_formats.dotenv import extract_dotenv
from source.kg.extraction.file_formats.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigDotenvAdapter:
    capability = AdapterCapability(
        name="config-dotenv",
        languages=("config",),
        file_kinds=("env", "config"),
        framework_tags=("dotenv",),
        produces_predicates=("REFERENCES_DOMAIN", "REFERENCES_ENV_VAR"),
        produces_entity_kinds=("Domain", "EnvVar"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        extract_dotenv(repo, scannable_config_files(repo, ctx), service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_DOTENV_ADAPTER = ConfigDotenvAdapter()
