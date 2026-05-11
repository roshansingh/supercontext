from __future__ import annotations

import json
import re

from source.kg.extraction.config.channel_normalization import (
    add_event_channel_reference,
    normalized_channels_in_text,
    normalized_ini_queue_channels,
    normalize_sqs_arn,
)
from source.kg.extraction.config.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    event_channel_entity,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot


SERVERLESS_ROUTE_RE = re.compile(r"^\s*route:\s*['\"]?([^'\"\n]+)")
SERVERLESS_HANDLER_RE = re.compile(r"^\s*handler:\s*['\"]?([^'\"\n]+)")


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
        _add_apache_vhost_coverage_if_present(scanned, build, resolved_tenant_id, repo)
        if include_event_channel_references and scanned.path.name != "zappa_settings.json":
            _extract_queue_lines(repo, scanned, service_entity, build, resolved_tenant_id)
        _extract_serverless_routes(repo, scanned, service_entity, build, resolved_tenant_id)
        if scanned.path.name == "zappa_settings.json":
            _add_zappa_event_source_coverage_if_present(scanned, build, resolved_tenant_id, repo)


def _add_apache_vhost_coverage_if_present(
    scanned: ScannedFile,
    build: ConfigKgBuild,
    tenant_id: str,
    repo: RepoSnapshot,
) -> None:
    if not _looks_like_apache_vhost(scanned):
        return
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="ROUTES_DOMAIN_TO_DEPLOY",
            scope_ref={
                "repo": repo.name,
                "file_path": scanned.relative_path,
                "reason": "no_oss_adapter_for_apache_vhosts",
            },
            state="uninstrumented",
            source_system=CONFIG_SOURCE_SYSTEM,
        )
    )


def _looks_like_apache_vhost(scanned: ScannedFile) -> bool:
    has_vhost_block = False
    has_vhost_directive = False
    for line in scanned.lines:
        stripped = line.strip().lower()
        if stripped.startswith("<virtualhost") or stripped.startswith("</virtualhost"):
            has_vhost_block = True
            continue
        if not stripped:
            continue
        directive = stripped.split(maxsplit=1)[0]
        if directive in {"servername", "serveralias", "wsgiscriptalias"}:
            has_vhost_directive = True
    return has_vhost_block and has_vhost_directive


def _add_zappa_event_source_coverage_if_present(
    scanned: ScannedFile,
    build: ConfigKgBuild,
    tenant_id: str,
    repo: RepoSnapshot,
) -> None:
    if not _looks_like_zappa_event_sources(scanned):
        return
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="CONSUMES_EVENT",
            scope_ref={
                "repo": repo.name,
                "file_path": scanned.relative_path,
                "reason": "no_oss_adapter_for_zappa_event_sources",
            },
            state="uninstrumented",
            source_system=CONFIG_SOURCE_SYSTEM,
        )
    )


def _looks_like_zappa_event_sources(scanned: ScannedFile) -> bool:
    try:
        data = json.loads(scanned.text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    for stage_config in data.values():
        if not isinstance(stage_config, dict):
            continue
        events = stage_config.get("events")
        if not isinstance(events, list):
            continue
        for event_source in events:
            if not isinstance(event_source, dict):
                continue
            source = event_source.get("event_source")
            if not isinstance(source, dict):
                continue
            arn = source.get("arn")
            if isinstance(arn, str) and normalize_sqs_arn(arn) is not None:
                return True
    return False


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


def _extract_serverless_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    if scanned.path.suffix not in {".yml", ".yaml"}:
        return
    pending_handler: tuple[int, str] | None = None
    for line_number, line in enumerate(scanned.lines, start=1):
        handler_match = SERVERLESS_HANDLER_RE.match(line)
        if handler_match:
            pending_handler = (line_number, handler_match.group(1).strip())
            continue
        route_match = SERVERLESS_ROUTE_RE.match(line)
        if not route_match:
            continue
        route = route_match.group(1).strip()
        endpoint = endpoint_entity(repo, "ANY", route, tenant_id=tenant_id)
        add_entity_evidence(build, repo, endpoint, scanned.path, line_number)
        qualifier: JsonObject = {"source_kind": "serverless_route", "path": scanned.relative_path}
        if pending_handler:
            qualifier["handler"] = pending_handler[1]
        add_fact(build, "EXPOSES_ENDPOINT", service_entity, endpoint, repo, scanned.path, line_number, qualifier=qualifier)
        channel = event_channel_entity(
            repo,
            "websocket",
            route,
            tenant_id=tenant_id,
            properties={"raw_literal": route, "source_kind": "serverless_route", "path": scanned.relative_path},
        )
        add_entity_evidence(build, repo, channel, scanned.path, line_number)
        add_fact(build, "CONSUMES_EVENT", service_entity, channel, repo, scanned.path, line_number, qualifier=qualifier)
