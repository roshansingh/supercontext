from __future__ import annotations

import json
import re
from pathlib import Path

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
from source.kg.models import Entity, JsonObject
from source.kg.repo_source import RepoSnapshot


APACHE_SERVER_NAME_RE = re.compile(r"^\s*Server(?:Name|Alias)\s+([^\s#]+)")
APACHE_WSGI_RE = re.compile(r"^\s*WSGIScriptAlias\s+\S+\s+([^\s#]+)")
QUEUE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*['\"]?([A-Za-z0-9_.:/-]*(?:queue|sqs|campaign|email)[A-Za-z0-9_.:/-]*)", re.IGNORECASE)
SQS_ARN_RE = re.compile(r"arn:aws:sqs:[A-Za-z0-9-]+:\d+:([A-Za-z0-9_.-]+)")
SERVERLESS_ROUTE_RE = re.compile(r"^\s*route:\s*['\"]?([^'\"\n]+)")
SERVERLESS_HANDLER_RE = re.compile(r"^\s*handler:\s*['\"]?([^'\"\n]+)")
APACHE_VHOST_START_RE = re.compile(r"^\s*<VirtualHost\b", re.IGNORECASE)
APACHE_VHOST_END_RE = re.compile(r"^\s*</VirtualHost\s*>", re.IGNORECASE)


def extract_deploy_events(repo: RepoSnapshot, files: list[ScannedFile], service_entity: Entity, build: ConfigKgBuild) -> None:
    for scanned in files:
        _extract_apache(repo, scanned, service_entity, build)
        _extract_queue_lines(repo, scanned, service_entity, build)
        _extract_serverless_routes(repo, scanned, service_entity, build)
        if scanned.path.name == "zappa_settings.json":
            _extract_zappa_event_sources(repo, scanned, service_entity, build)


def _extract_apache(repo: RepoSnapshot, scanned: ScannedFile, service_entity: Entity, build: ConfigKgBuild) -> None:
    for domains_by_line, wsgi_by_line in _apache_vhost_blocks(scanned):
        for line_number, domain in domains_by_line:
            _add_apache_domain_routes(repo, scanned, service_entity, build, line_number, domain, wsgi_by_line)


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
) -> None:
    domain_ref = domain_entity(repo, domain)
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
        target = deploy_target_entity(repo, "wsgi", wsgi_path)
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


def _extract_queue_lines(repo: RepoSnapshot, scanned: ScannedFile, service_entity: Entity, build: ConfigKgBuild) -> None:
    for line_number, line in enumerate(scanned.lines, start=1):
        for queue_name in SQS_ARN_RE.findall(line):
            _add_event_reference(repo, scanned, line_number, service_entity, build, queue_name, "sqs", "sqs_arn")
        match = QUEUE_ASSIGN_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip().strip("'\",")
        if value.startswith("arn:aws:sqs"):
            arn_match = SQS_ARN_RE.search(value)
            value = arn_match.group(1) if arn_match else value
        _add_event_reference(repo, scanned, line_number, service_entity, build, value, "sqs", key)


def _extract_serverless_routes(repo: RepoSnapshot, scanned: ScannedFile, service_entity: Entity, build: ConfigKgBuild) -> None:
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
        endpoint = endpoint_entity(repo, "ANY", route)
        add_entity_evidence(build, repo, endpoint, scanned.path, line_number)
        qualifier: JsonObject = {"source_kind": "serverless_route", "path": scanned.relative_path}
        if pending_handler:
            qualifier["handler"] = pending_handler[1]
        add_fact(build, "EXPOSES_ENDPOINT", service_entity, endpoint, repo, scanned.path, line_number, qualifier=qualifier)
        channel = event_channel_entity(repo, route, "websocket")
        add_entity_evidence(build, repo, channel, scanned.path, line_number)
        add_fact(build, "CONSUMES_EVENT", service_entity, channel, repo, scanned.path, line_number, qualifier=qualifier)


def _extract_zappa_event_sources(repo: RepoSnapshot, scanned: ScannedFile, service_entity: Entity, build: ConfigKgBuild) -> None:
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
            arn_match = SQS_ARN_RE.search(arn)
            if not arn_match:
                continue
            queue_name = arn_match.group(1)
            line_number = _line_number_for(scanned, queue_name)
            channel = event_channel_entity(repo, queue_name, "sqs")
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
                },
            )


def _add_event_reference(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    service_entity: Entity,
    build: ConfigKgBuild,
    channel_name: str,
    broker_kind: str,
    source_kind: str,
) -> None:
    if not channel_name:
        return
    channel = event_channel_entity(repo, channel_name, broker_kind)
    add_entity_evidence(build, repo, channel, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_EVENT_CHANNEL",
        service_entity,
        channel,
        repo,
        scanned.path,
        line_number,
        qualifier={"source_kind": source_kind, "path": scanned.relative_path},
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
