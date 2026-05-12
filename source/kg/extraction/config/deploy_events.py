"""Legacy queue-line config extraction used by the static config monolith."""

from __future__ import annotations

from source.kg.extraction.config.channel_normalization import (
    add_event_channel_reference,
    normalized_channels_in_text,
    normalized_ini_queue_channels,
)
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot


def extract_deploy_events(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
    *,
    include_event_channel_references: bool = False,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for scanned in files:
        if include_event_channel_references and scanned.path.name != "zappa_settings.json":
            _extract_queue_lines(repo, scanned, service_entity, build, resolved_tenant_id)


def _extract_queue_lines(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for line_number, channel in normalized_ini_queue_channels(scanned):
        add_event_channel_reference(repo, scanned, line_number, service_entity, build, channel, "ini_queue_config", tenant_id)
    for line_number, line in enumerate(scanned.lines, start=1):
        for channel in normalized_channels_in_text(line):
            add_event_channel_reference(repo, scanned, line_number, service_entity, build, channel, "transport_literal", tenant_id)
