from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters.config_shared import scan_coverage_rows, scannable_config_files
from source.kg.extraction.config.channel_normalization import (
    add_event_channel_reference,
    normalized_channels_in_text,
    normalized_ini_queue_channels,
)
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
)
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext


@dataclass(frozen=True)
class EventChannelNormalizerAdapter:
    capability = AdapterCapability(
        name="event-channel-normalizer",
        languages=("config",),
        file_kinds=("config", "ini", "json", "yaml", "yml"),
        framework_tags=("sqs", "sns"),
        produces_predicates=("REFERENCES_EVENT_CHANNEL",),
        produces_entity_kinds=("EventChannel",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        for scanned in scannable_config_files(repo, ctx):
            # Zappa event sources have a dedicated deploy-events parser that
            # emits authoritative CONSUMES_EVENT facts from the JSON structure.
            if scanned.path.name == "zappa_settings.json":
                continue
            _extract_event_channel_references(repo, scanned, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage) + scan_coverage_rows(repo, ctx),
        )


def _extract_event_channel_references(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for line_number, channel in normalized_ini_queue_channels(scanned):
        add_event_channel_reference(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            channel,
            "ini_queue_config",
            tenant_id,
        )
    for line_number, line in enumerate(scanned.lines, start=1):
        for channel in normalized_channels_in_text(line):
            add_event_channel_reference(
                repo,
                scanned,
                line_number,
                service_entity,
                build,
                channel,
                "transport_literal",
                tenant_id,
            )


EVENT_CHANNEL_NORMALIZER_ADAPTER = EventChannelNormalizerAdapter()
