"""Build PRODUCES_EVENT / CONSUMES_EVENT facts from parsed TS/JS message-broker events.

Consumes the ``message_events`` rows emitted by ``ts_parser.mjs`` (NestJS microservice
``@EventPattern``/``@MessagePattern`` consumers and ClientProxy/ClientKafka ``.emit``/``.send``
producers) and attaches them to the repo's Service entity via a shared EventChannel keyed by
broker + channel name. Channels that could not be resolved to a string literal at parse time
become a loud-refusal ``coverage`` row instead of a guessed channel.
"""

from __future__ import annotations

from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    add_entity_evidence,
    add_fact,
    event_channel_entity,
)


_EVENT_PREDICATES = {"PRODUCES_EVENT", "CONSUMES_EVENT"}


def extract_typescript_message_events(
    repo: RepoSnapshot,
    parsed_files: dict[str, object],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(parsed_file, dict):
            continue
        file_path = repo.root / str(relative_path)
        for row in parsed_file.get("message_events", []):
            if not isinstance(row, dict):
                continue
            predicate = str(row.get("predicate", ""))
            if predicate not in _EVENT_PREDICATES:
                continue
            broker_kind = str(row.get("broker") or "nestjs")
            line = int(row.get("line") or 1)
            channel_address = row.get("channel")
            if not isinstance(channel_address, str) or not channel_address:
                build.coverage.append(
                    Coverage(
                        tenant_id=tenant_id,
                        predicate=predicate,
                        scope_ref={
                            "repo": repo.name,
                            "path": str(relative_path),
                            "line": line,
                            "reason": "unresolved_event_channel",
                            "broker_kind": broker_kind,
                            "api": row.get("api"),
                            "raw": row.get("channel_raw"),
                        },
                        state="partially_instrumented",
                        source_system=CONFIG_SOURCE_SYSTEM,
                    )
                )
                continue
            channel = event_channel_entity(
                repo,
                broker_kind,
                channel_address,
                tenant_id=tenant_id,
                properties={"channel_address": channel_address},
            )
            add_entity_evidence(build, repo, channel, file_path, line, line)
            add_fact(
                build,
                predicate,
                service_entity,
                channel,
                repo,
                file_path,
                line,
                line,
                qualifier=_qualifier(broker_kind, channel_address, row),
            )


def _qualifier(broker_kind: str, channel_address: str, row: JsonObject) -> JsonObject:
    return {
        "source_kind": "typescript_message_event",
        "api": row.get("api"),
        "broker_kind": broker_kind,
        "channel_address": channel_address,
        "normalized_channel": channel_address,
        "subject_class": row.get("subject_class"),
    }
