from __future__ import annotations

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats._shared.common import ConfigKgBuild, ScannedFile, add_entity_evidence, add_fact, domain_entity
from source.kg.file_formats.domain_env import DOMAIN_RE


def extract_cname_domains(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for scanned in files:
        if scanned.path.name != "CNAME":
            continue
        for line_number, line in enumerate(scanned.lines, start=1):
            domain = _parse_cname_domain(line)
            if domain is None:
                continue
            entity = domain_entity(repo, domain, resolved_tenant_id)
            add_entity_evidence(build, repo, entity, scanned.path, line_number)
            add_fact(
                build,
                "REFERENCES_DOMAIN",
                service_entity,
                entity,
                repo,
                scanned.path,
                line_number,
                qualifier={"literal": domain, "path": scanned.relative_path, "source_kind": "static_site_cname"},
            )


def _parse_cname_domain(line: str) -> str | None:
    value = line.strip().strip("'\"`<>()[]{}.,;")
    if not value or value.startswith("#") or "/" in value or "://" in value:
        return None
    match = DOMAIN_RE.fullmatch(value.lower())
    return match.group(0) if match else None
