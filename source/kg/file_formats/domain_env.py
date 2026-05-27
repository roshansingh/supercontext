from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from source.kg.file_formats._shared.common import (
    CONFIG_KEY_HINTS,
    ConfigKgBuild,
    IGNORED_DOMAIN_SUFFIXES,
    ScannedFile,
    SECRET_KEY_HINTS,
    add_entity_evidence,
    add_fact,
    domain_entity,
    env_var_entity,
    is_dotenv_file,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot


URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+")
DOMAIN_RE = re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
JS_ENV_RE = re.compile(r"\b(?:process\.env|import\.meta\.env)\.([A-Za-z_][A-Za-z0-9_]*)")
PY_ENV_RE = re.compile(r"\b(?:os\.environ(?:\.get)?|getenv)\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
ENV_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*['\"]?([^'\"#\n]+)")

def extract_domain_env(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for scanned in files:
        if is_dotenv_file(scanned):
            continue
        for line_number, line in enumerate(scanned.lines, start=1):
            _extract_domains(repo, scanned, line_number, line, service_entity, build, resolved_tenant_id)
            _extract_env_references(repo, scanned, line_number, line, service_entity, build, resolved_tenant_id)
            _extract_env_assignments(repo, scanned, line_number, line, service_entity, build, resolved_tenant_id)


def _extract_domains(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    # Domain-env extraction is line scoped: a config-like key on the line makes
    # all URL/domain literals on that line runtime configuration leads.
    source_kind = "domain_env" if _line_has_domain_hint(line) else "source_domain_literal"
    for url in URL_RE.findall(line):
        clean_url = _clean_url_literal(url)
        parsed = _safe_parse_url(clean_url)
        if parsed is None:
            continue
        hostname = _safe_hostname(parsed)
        if hostname:
            _add_domain_reference(
                repo,
                scanned,
                line_number,
                service_entity,
                build,
                hostname,
                clean_url,
                tenant_id,
                source_kind=source_kind,
            )
    for domain in DOMAIN_RE.findall(line):
        if _looks_like_code_file(domain):
            continue
        if "://" in line or _line_has_domain_hint(line):
            _add_domain_reference(
                repo,
                scanned,
                line_number,
                service_entity,
                build,
                domain,
                domain,
                tenant_id,
                source_kind=source_kind,
            )


def _extract_env_references(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for env_name in sorted(set(JS_ENV_RE.findall(line) + PY_ENV_RE.findall(line))):
        env_entity = env_var_entity(repo, env_name, tenant_id)
        add_entity_evidence(build, repo, env_entity, scanned.path, line_number)
        add_fact(
            build,
            "REFERENCES_ENV_VAR",
            service_entity,
            env_entity,
            repo,
            scanned.path,
            line_number,
            qualifier={"name": env_name, "reference_kind": "code_access"},
        )


def _extract_env_assignments(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    match = ENV_ASSIGN_RE.match(line)
    if not match:
        return
    key = match.group(1)
    value = match.group(2).strip()
    if not _is_config_key(key):
        return

    env_entity = env_var_entity(repo, key, tenant_id)
    add_entity_evidence(build, repo, env_entity, scanned.path, line_number)
    qualifier = {"name": key, "reference_kind": "config_assignment", "value_kind": _value_kind(key, value)}
    if qualifier["value_kind"] in {"domain", "url"}:
        qualifier["safe_literal"] = _safe_config_literal(value)
    add_fact(build, "REFERENCES_ENV_VAR", service_entity, env_entity, repo, scanned.path, line_number, qualifier=qualifier)

    for url in URL_RE.findall(value):
        clean_url = _clean_url_literal(url)
        parsed = _safe_parse_url(clean_url)
        if parsed is None:
            continue
        hostname = _safe_hostname(parsed)
        if hostname:
            _add_domain_reference(
                repo,
                scanned,
                line_number,
                env_entity,
                build,
                hostname,
                clean_url,
                tenant_id,
                source_kind="domain_env",
            )
    for domain in DOMAIN_RE.findall(value):
        if not _looks_like_code_file(domain):
            _add_domain_reference(
                repo,
                scanned,
                line_number,
                env_entity,
                build,
                domain,
                domain,
                tenant_id,
                source_kind="domain_env",
            )


def _add_domain_reference(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    subject: Entity,
    build: ConfigKgBuild,
    domain: str,
    literal: str,
    tenant_id: str,
    source_kind: str,
) -> None:
    domain_ref = _normalize_domain_ref(domain)
    if not domain_ref:
        return
    entity = domain_entity(repo, domain_ref, tenant_id)
    add_entity_evidence(build, repo, entity, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_DOMAIN",
        subject,
        entity,
        repo,
        scanned.path,
        line_number,
        qualifier={"literal": _safe_config_literal(literal), "path": scanned.relative_path, "source_kind": source_kind},
    )


def _normalize_domain_ref(domain: str) -> str:
    value = domain.strip().lower().strip(" \t\r\n'\"`<>()[]{}.,;")
    match = DOMAIN_RE.search(value)
    return match.group(0) if match else value


def _safe_config_literal(value: str) -> str:
    parsed = _safe_parse_url(_clean_url_literal(value))
    if parsed is not None and parsed.scheme in {"http", "https"}:
        hostname = _safe_hostname(parsed)
        if not hostname:
            return ""
        netloc = _normalize_domain_ref(hostname)
        if not netloc:
            return ""
        port = _safe_port(parsed)
        if port:
            netloc = f"{netloc}:{port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))

    domain_match = DOMAIN_RE.search(value)
    if domain_match:
        return _normalize_domain_ref(domain_match.group(0))
    return ""


def _line_has_domain_hint(line: str) -> bool:
    upper = line.upper()
    return any(hint in upper for hint in CONFIG_KEY_HINTS)


def _looks_like_code_file(value: str) -> bool:
    return value.endswith(IGNORED_DOMAIN_SUFFIXES)


def _safe_parse_url(value: str):
    try:
        return urlparse(value)
    except ValueError:
        return None


def _clean_url_literal(value: str) -> str:
    return value.strip().strip("'\"`<>()[]{}.,;")


def _safe_hostname(parsed_url) -> str | None:
    try:
        return parsed_url.hostname
    except ValueError:
        return None


def _safe_port(parsed_url) -> int | None:
    try:
        return parsed_url.port
    except ValueError:
        return None


def _is_config_key(key: str) -> bool:
    upper = key.upper()
    return any(hint in upper for hint in CONFIG_KEY_HINTS)


def _value_kind(key: str, value: str) -> str:
    upper_key = key.upper()
    if any(hint in upper_key for hint in SECRET_KEY_HINTS):
        return "secret_like"
    if URL_RE.search(value):
        return "url"
    if DOMAIN_RE.search(value):
        return "domain"
    return "literal"
