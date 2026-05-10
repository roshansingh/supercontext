from __future__ import annotations

from dataclasses import dataclass

from source.kg.extraction.adapters.config_shared import scannable_config_files
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ConfigKgBuild
from source.kg.extraction.config.domain_env import extract_domain_env
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigDomainEnvAdapter:
    capability = AdapterCapability(
        name="config-domain-env",
        languages=("config", "javascript", "python", "typescript"),
        file_kinds=("config", "javascript", "python", "typescript"),
        framework_tags=("domain", "env"),
        produces_predicates=("REFERENCES_DOMAIN", "REFERENCES_ENV_VAR"),
        produces_entity_kinds=("Domain", "EnvVar"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo)
        extract_domain_env(repo, scannable_config_files(repo, ctx), service_entity, build)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


CONFIG_DOMAIN_ENV_ADAPTER = ConfigDomainEnvAdapter()
