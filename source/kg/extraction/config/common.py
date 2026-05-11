from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from source.kg.core.models import Coverage, Entity, Evidence, EvidenceDerivationClass, Fact, JsonObject
from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id


CONFIG_SOURCE_SYSTEM = "static_config_v0"

CONFIG_KEY_HINTS = ("API", "BASE", "DOMAIN", "HOST", "URL", "WS")
SECRET_KEY_HINTS = ("KEY", "PASS", "PASSWORD", "SECRET", "TOKEN")
IGNORED_DOMAIN_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx")

CONFIG_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".cjs",
    ".env",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".py",
    ".tf",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
IGNORED_CONFIG_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "yarn.lock",
}
# Keep config scanning bounded: files above 2 MB are usually generated
# templates, caches, or artifacts, and now emit coverage instead of loading.
MAX_SCAN_BYTES = 2_000_000


@dataclass
class ConfigKgBuild:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    relative_path: str
    text: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ConfigScanResult:
    files: tuple[ScannedFile, ...]
    coverage: tuple[Coverage, ...]


def scan_config_files(repo: RepoSnapshot, tenant_id: str | None = None) -> ConfigScanResult:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    files: list[ScannedFile] = []
    coverage: list[Coverage] = []
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo.root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in filenames:
            path = Path(dirpath) / filename
            if filename in IGNORED_CONFIG_FILENAMES:
                continue
            if path.suffix not in CONFIG_EXTENSIONS and not is_dotenv_filename(filename):
                continue
            candidates.append(path)

    for path in sorted(candidates, key=lambda candidate: str(candidate.relative_to(repo.root))):
        relative = path.relative_to(repo.root)
        size_bytes = path.stat().st_size
        if size_bytes > MAX_SCAN_BYTES:
            coverage.append(
                Coverage(
                    tenant_id=resolved_tenant_id,
                    predicate="CONFIG_SCAN",
                    scope_ref={
                        "repo": repo.name,
                        "file_path": str(relative),
                        "reason": "exceeds_max_scan_bytes",
                        "size_bytes": size_bytes,
                        "max_scan_bytes": MAX_SCAN_BYTES,
                    },
                    state="uninstrumented",
                    source_system=CONFIG_SOURCE_SYSTEM,
                )
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        files.append(ScannedFile(path=path, relative_path=str(relative), text=text, lines=tuple(text.splitlines())))
    return ConfigScanResult(files=tuple(files), coverage=tuple(coverage))


def iter_scannable_files(repo: RepoSnapshot) -> list[ScannedFile]:
    return list(scan_config_files(repo).files)


def is_dotenv_file(scanned: ScannedFile) -> bool:
    return is_dotenv_filename(scanned.path.name)


def is_dotenv_filename(filename: str) -> bool:
    return filename == ".env" or filename.startswith(".env.")


def add_entity_evidence(
    build: ConfigKgBuild,
    repo: RepoSnapshot,
    entity: Entity,
    file_path: Path,
    line_start: int,
    line_end: int | None = None,
) -> None:
    build.entities.append(entity)
    build.evidence.append(
        Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="deterministic_static",
            source_system=CONFIG_SOURCE_SYSTEM,
            source_ref={"extractor": CONFIG_SOURCE_SYSTEM, "entity_kind": entity.kind},
            bytes_ref=bytes_ref(repo, file_path, line_start, line_end or line_start),
            confidence=1.0,
        )
    )


def add_fact(
    build: ConfigKgBuild,
    predicate: str,
    subject: Entity,
    object_: Entity,
    repo: RepoSnapshot,
    file_path: Path,
    line_start: int,
    line_end: int | None = None,
    qualifier: JsonObject | None = None,
    derivation_class: EvidenceDerivationClass = "deterministic_static",
) -> None:
    fact = Fact(predicate=predicate, subject_id=subject.entity_id, object_id=object_.entity_id, qualifier=qualifier or {})
    build.facts.append(fact)
    build.evidence.append(
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class=derivation_class,
            source_system=CONFIG_SOURCE_SYSTEM,
            source_ref={"extractor": CONFIG_SOURCE_SYSTEM, "predicate": predicate},
            bytes_ref=bytes_ref(repo, file_path, line_start, line_end or line_start),
            confidence=1.0,
        )
    )


def bytes_ref(repo: RepoSnapshot, file_path: Path, line_start: int, line_end: int) -> JsonObject:
    return {
        "repo": repo.name,
        "commit_sha": repo.commit_sha,
        "path": str(file_path.relative_to(repo.root)),
        "line_start": line_start,
        "line_end": line_end,
    }


def domain_entity(repo: RepoSnapshot, domain: str, tenant_id: str | None = None) -> Entity:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    return Entity(
        kind="Domain",
        identity={"tenant_id": resolved_tenant_id, "repo": repo.name, "name": domain.lower()},
        properties={},
    )


def env_var_entity(repo: RepoSnapshot, name: str, tenant_id: str | None = None) -> Entity:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    return Entity(
        kind="EnvVar",
        identity={"tenant_id": resolved_tenant_id, "repo": repo.name, "name": name},
        properties={},
    )


def endpoint_entity(
    repo: RepoSnapshot,
    method: str,
    path: str,
    host: str | None = None,
    *,
    tenant_id: str | None = None,
) -> Entity:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    return Entity(
        kind="Endpoint",
        identity={
            "tenant_id": resolved_tenant_id,
            "repo": repo.name,
            "protocol": "http",
            "method": method.upper() if method else "ANY",
            "path": normalize_endpoint_path(path),
            "host": host or None,
        },
        properties={},
    )


def event_channel_entity(
    _repo: RepoSnapshot,
    broker_kind: str,
    channel_address: str,
    *,
    tenant_id: str | None = None,
    properties: JsonObject | None = None,
    canonical_status: Literal["canonical", "candidate", "demoted"] = "canonical",
) -> Entity:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    return Entity(
        kind="EventChannel",
        identity={"tenant_id": resolved_tenant_id, "broker_kind": broker_kind, "channel_address": channel_address},
        properties=properties or {},
        canonical_status=canonical_status,
    )


def deploy_target_entity(repo: RepoSnapshot, target_type: str, target: str, tenant_id: str | None = None) -> Entity:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    return Entity(
        kind="DeployTarget",
        identity={"tenant_id": resolved_tenant_id, "repo": repo.name, "type": target_type, "target": target},
        properties={},
    )


def normalize_endpoint_path(path: str) -> str:
    value = path.strip().strip("'\"`")
    if not value:
        return "/"
    if not value.startswith("/") and not value.startswith("http"):
        value = "/" + value
    return value
