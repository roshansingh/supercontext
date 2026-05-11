from __future__ import annotations

import json
import re
from pathlib import Path

from source.kg.extraction.config.channel_normalization import (
    add_event_channel_reference,
    normalized_channels_in_text,
    normalized_ini_queue_channels,
    normalize_sqs_arn,
)
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
    endpoint_entity,
    event_channel_entity,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.core.models import Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot


APACHE_SERVER_NAME_RE = re.compile(r"^\s*Server(?:Name|Alias)\s+([^\s#]+)")
APACHE_WSGI_RE = re.compile(r"^\s*WSGIScriptAlias\s+\S+\s+([^\s#]+)")
SERVERLESS_ROUTE_RE = re.compile(r"^\s*route:\s*['\"]?([^'\"\n]+)")
SERVERLESS_HANDLER_RE = re.compile(r"^\s*handler:\s*['\"]?([^'\"\n]+)")
APACHE_VHOST_START_RE = re.compile(r"^\s*<VirtualHost\b", re.IGNORECASE)
APACHE_VHOST_END_RE = re.compile(r"^\s*</VirtualHost\s*>", re.IGNORECASE)


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
        _extract_apache(repo, scanned, service_entity, build, resolved_tenant_id)
        if include_event_channel_references and scanned.path.name != "zappa_settings.json":
            _extract_queue_lines(repo, scanned, service_entity, build, resolved_tenant_id)
        _extract_serverless_routes(repo, scanned, service_entity, build, resolved_tenant_id)
        if scanned.path.name == "zappa_settings.json":
            _extract_zappa_event_sources(repo, scanned, service_entity, build, resolved_tenant_id)


def _extract_apache(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for domains_by_line, wsgi_by_line in _apache_vhost_blocks(scanned):
        for line_number, domain in domains_by_line:
            _add_apache_domain_routes(repo, scanned, service_entity, build, line_number, domain, wsgi_by_line, tenant_id)


def _apache_vhost_blocks(scanned: ScannedFile) -> list[tuple[list[tuple[int, str]], list[tuple[int, str]]]]:
    blocks: list[tuple[list[tuple[int, str]], list[tuple[int, str]]]] = []
    domains_by_line: list[tuple[int, str]] = []
    wsgi_by_line: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal domains_by_line, wsgi_by_line
        if domains_by_line or wsgi_by_line:
            blocks.append((domains_by_line, wsgi_by_line))
        domains_by_line = []
        wsgi_by_line = []

    for line_number, line in enumerate(scanned.lines, start=1):
        if APACHE_VHOST_START_RE.match(line):
            flush()
            continue
        if APACHE_VHOST_END_RE.match(line):
            flush()
            continue

        server_match = APACHE_SERVER_NAME_RE.match(line)
        if server_match:
            domains_by_line.append((line_number, server_match.group(1)))
        wsgi_match = APACHE_WSGI_RE.match(line)
        if wsgi_match:
            wsgi_by_line.append((line_number, wsgi_match.group(1)))

    flush()
    return blocks


def _add_apache_domain_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    line_number: int,
    domain: str,
    wsgi_by_line: list[tuple[int, str]],
    tenant_id: str,
) -> None:
    domain_ref = domain_entity(repo, domain, tenant_id)
    add_entity_evidence(build, repo, domain_ref, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_DOMAIN",
        service_entity,
        domain_ref,
        repo,
        scanned.path,
        line_number,
        qualifier={"source_kind": "apache_server_name", "path": scanned.relative_path},
    )
    for wsgi_line, wsgi_path in wsgi_by_line:
        target = deploy_target_entity(repo, "wsgi", wsgi_path, tenant_id)
        add_entity_evidence(build, repo, target, scanned.path, wsgi_line)
        qualifier: JsonObject = {"source_kind": "apache_vhost"}
        repo_hint = _repo_hint_from_path(wsgi_path)
        if repo_hint:
            qualifier["target_repo_hint"] = repo_hint
        add_fact(
            build,
            "ROUTES_DOMAIN_TO_DEPLOY",
            domain_ref,
            target,
            repo,
            scanned.path,
            min(line_number, wsgi_line),
            max(line_number, wsgi_line),
            qualifier=qualifier,
        )


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


def _extract_zappa_event_sources(
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


def _repo_hint_from_path(path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) >= 4 and parts[1] == "home":
        return parts[3]
    return None


def _line_number_for(scanned: ScannedFile, needle: str) -> int:
    for line_number, line in enumerate(scanned.lines, start=1):
        if needle in line:
            return line_number
    return 1
