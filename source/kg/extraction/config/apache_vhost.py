from __future__ import annotations

"""Apache vhost extraction for the narrow v1 WSGI routing contract.

This parser intentionally recognizes only VirtualHost blocks with ServerName or
ServerAlias plus WSGIScriptAlias. Server-only vhosts, domainless WSGI aliases,
ProxyPass, Location, Directory, and malformed/unclosed blocks are out of v1.
"""

from dataclasses import dataclass, field

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
)


@dataclass
class _VhostBlock:
    domains_by_line: list[tuple[int, str]] = field(default_factory=list)
    wsgi_by_line: list[tuple[int, str]] = field(default_factory=list)


def extract_apache_vhost_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for block in _apache_vhost_blocks(scanned):
        if not block.domains_by_line or not block.wsgi_by_line:
            continue
        for line_number, domain in block.domains_by_line:
            _add_apache_domain_routes(repo, scanned, service_entity, build, line_number, domain, block.wsgi_by_line, tenant_id)


def _apache_vhost_blocks(scanned: ScannedFile) -> list[_VhostBlock]:
    blocks: list[_VhostBlock] = []
    current: _VhostBlock | None = None

    for line_number, raw_line in enumerate(scanned.lines, start=1):
        line = _strip_inline_comment(raw_line).strip()
        if not line:
            continue

        lower = line.lower()
        if lower.startswith("<virtualhost"):
            # Malformed nested/unclosed blocks fail closed instead of emitting
            # partial route facts without a complete block boundary.
            current = _VhostBlock()
            continue
        if lower.startswith("</virtualhost"):
            if current is not None:
                blocks.append(current)
                current = None
            continue
        if current is None:
            continue

        tokens = line.split()
        if not tokens:
            continue
        directive = tokens[0].lower()
        if directive == "servername" and len(tokens) >= 2:
            current.domains_by_line.append((line_number, _strip_quotes(tokens[1])))
        elif directive == "serveralias":
            for token in tokens[1:]:
                current.domains_by_line.append((line_number, _strip_quotes(token)))
        elif directive == "wsgiscriptalias" and len(tokens) >= 3:
            current.wsgi_by_line.append((line_number, _strip_quotes(tokens[2])))

    return blocks


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif char == "#" and quote is None:
            return line[:index]
    return line


def _strip_quotes(value: str) -> str:
    return value.strip().strip("'\"")


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
    if not domain:
        return
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
        if not wsgi_path:
            continue
        target = deploy_target_entity(repo, "wsgi", wsgi_path, tenant_id)
        add_entity_evidence(build, repo, target, scanned.path, wsgi_line)
        add_fact(
            build,
            "ROUTES_DOMAIN_TO_DEPLOY",
            domain_ref,
            target,
            repo,
            scanned.path,
            min(line_number, wsgi_line),
            max(line_number, wsgi_line),
            qualifier={"source_kind": "apache_vhost"},
        )
