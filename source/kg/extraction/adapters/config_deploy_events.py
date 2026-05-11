from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.extraction.config.common import ConfigKgBuild
from source.kg.extraction.config.deploy_events import extract_deploy_events
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class ConfigDeployEventsAdapter:
    capability = AdapterCapability(
        name="config-deploy-events",
        languages=("config",),
        file_kinds=("config", "ini", "json", "yaml", "yml"),
        framework_tags=("serverless", "zappa", "sqs", "sns"),
        produces_predicates=(
            "EXPOSES_ENDPOINT",
            "CONSUMES_EVENT",
        ),
        produces_entity_kinds=("Endpoint", "EventChannel"),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        extract_deploy_events(
            repo,
            scannable_config_files(repo, ctx),
            service_entity,
            build,
            ctx.tenant_id,
            include_event_channel_references=False,
        )
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


CONFIG_DEPLOY_EVENTS_ADAPTER = ConfigDeployEventsAdapter()
