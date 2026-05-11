from __future__ import annotations

import re
from pathlib import Path

from source.kg.core.models import Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
)


# This private extension keeps the old anchored Apache directive patterns
# verbatim so moving it out of OSS source does not also change goldset behavior.
APACHE_SERVER_NAME_RE = re.compile(r"^\s*Server(?:Name|Alias)\s+([^\s#]+)")
APACHE_WSGI_RE = re.compile(r"^\s*WSGIScriptAlias\s+\S+\s+([^\s#]+)")
APACHE_VHOST_START_RE = re.compile(r"^\s*<VirtualHost\b", re.IGNORECASE)
APACHE_VHOST_END_RE = re.compile(r"^\s*</VirtualHost\s*>", re.IGNORECASE)


def extract_apache_vhost_routes(
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


def _repo_hint_from_path(path: str) -> str | None:
    parts = Path(path).parts
    if len(parts) >= 4 and parts[1] == "home":
        return parts[3]
    return None
