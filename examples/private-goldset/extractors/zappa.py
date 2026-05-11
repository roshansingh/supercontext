from __future__ import annotations

import json

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.channel_normalization import normalize_sqs_arn
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    event_channel_entity,
)


def extract_zappa_event_sources(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    try:
        data = json.loads(scanned.text)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    for stage_name, stage_config in data.items():
        if not isinstance(stage_config, dict):
            continue
        for event_source in stage_config.get("events", []):
            if not isinstance(event_source, dict):
                continue
            arn = str(event_source.get("event_source", {}).get("arn") or "")
            function = str(event_source.get("function") or "")
            channel_ref = normalize_sqs_arn(arn)
            if channel_ref is None:
                continue
            line_number = _line_number_for(scanned, channel_ref.properties["raw_literal"])
            channel = event_channel_entity(
                repo,
                channel_ref.broker_kind,
                channel_ref.channel_address,
                tenant_id=tenant_id,
                properties=channel_ref.properties,
            )
            add_entity_evidence(build, repo, channel, scanned.path, line_number)
            add_fact(
                build,
                "CONSUMES_EVENT",
                service_entity,
                channel,
                repo,
                scanned.path,
                line_number,
                qualifier={
                    "source_kind": "zappa_event_source",
                    "stage": stage_name,
                    "function": function,
                    "path": scanned.relative_path,
                    "raw_literal": channel_ref.properties["raw_literal"],
                    "broker_kind": channel_ref.broker_kind,
                    "channel_address": channel_ref.channel_address,
                    "normalized_channel": channel_ref.channel_address,
                },
                derivation_class="authoritative_static",
            )


def _line_number_for(scanned: ScannedFile, needle: str) -> int:
    for line_number, line in enumerate(scanned.lines, start=1):
        if needle in line:
            return line_number
    return 1
