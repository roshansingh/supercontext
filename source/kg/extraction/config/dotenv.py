from __future__ import annotations

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    SECRET_KEY_HINTS,
    add_entity_evidence,
    add_fact,
    domain_entity,
    env_var_entity,
    is_dotenv_file,
)
from source.kg.extraction.config.domain_literals import (
    domain_from_value,
    safe_config_literal,
    value_kind,
)


def extract_dotenv(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    """Extract every valid assignment from dotenv files.

    Unlike inline config assignments in source files, dotenv files are config
    by definition, so assignments do not need name-hint filtering. Domain facts
    are emitted only when the assigned value is structurally a URL or domain.
    """
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for scanned in files:
        if not is_dotenv_file(scanned):
            continue
        for line_number, line in enumerate(scanned.lines, start=1):
            assignment = parse_dotenv_assignment(line)
            if assignment is None:
                continue
            key, value = assignment
            _add_env_assignment(repo, scanned, line_number, service_entity, build, key, value, resolved_tenant_id)


def parse_dotenv_assignment(line: str) -> tuple[str, str] | None:
    """Return a dotenv key/value pair, or None for blank/comment/malformed lines."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].lstrip()
    key, separator, raw_value = text.partition("=")
    if not separator:
        return None
    key = key.strip()
    if not _is_env_key(key):
        return None
    return key, _parse_dotenv_value(raw_value)


def _parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        return _quoted_value(value, value[0])
    return _unquoted_value(value)


def _quoted_value(value: str, quote: str) -> str:
    chars: list[str] = []
    escaped = False
    for char in value[1:]:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == quote:
            break
        chars.append(char)
    if escaped:
        chars.append("\\")
    return "".join(chars).strip()


def _unquoted_value(value: str) -> str:
    chars: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "#":
            break
        chars.append(char)
    if escaped:
        chars.append("\\")
    return "".join(chars).strip()


def _add_env_assignment(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    service_entity: Entity,
    build: ConfigKgBuild,
    key: str,
    value: str,
    tenant_id: str,
) -> None:
    env_entity = env_var_entity(repo, key, tenant_id)
    add_entity_evidence(build, repo, env_entity, scanned.path, line_number)
    current_value_kind = _value_kind(key, value)
    qualifier = {"name": key, "reference_kind": "config_assignment", "value_kind": current_value_kind}
    safe_literal = safe_config_literal(value) if current_value_kind in {"domain", "url"} else ""
    if safe_literal:
        qualifier["safe_literal"] = safe_literal
    add_fact(build, "REFERENCES_ENV_VAR", service_entity, env_entity, repo, scanned.path, line_number, qualifier=qualifier)

    domain_ref = domain_from_value(value)
    if domain_ref is None:
        return
    domain_ref_entity = domain_entity(repo, domain_ref, tenant_id)
    add_entity_evidence(build, repo, domain_ref_entity, scanned.path, line_number)
    add_fact(
        build,
        "REFERENCES_DOMAIN",
        env_entity,
        domain_ref_entity,
        repo,
        scanned.path,
        line_number,
        qualifier={"literal": safe_literal or domain_ref, "path": scanned.relative_path},
    )


def _is_env_key(key: str) -> bool:
    if not key:
        return False
    first = key[0]
    if not (first.isalpha() or first == "_"):
        return False
    return all(char.isalnum() or char == "_" for char in key[1:])


def _value_kind(key: str, value: str) -> str:
    upper_key = key.upper()
    return value_kind(value, secret_like=any(hint in upper_key for hint in SECRET_KEY_HINTS))
