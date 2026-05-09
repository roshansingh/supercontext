from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from source.kg.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.repo_source import IGNORED_DIRS, RepoSnapshot


TENANT_ID = "local-dev"
CONFIG_SOURCE_SYSTEM = "static_config_v0"

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


def iter_scannable_files(repo: RepoSnapshot) -> list[ScannedFile]:
    files: list[ScannedFile] = []
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo.root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in filenames:
            path = Path(dirpath) / filename
            if filename in IGNORED_CONFIG_FILENAMES:
                continue
            if path.suffix not in CONFIG_EXTENSIONS and not filename.startswith(".env"):
                continue
            candidates.append(path)

    for path in sorted(candidates, key=lambda candidate: str(candidate.relative_to(repo.root))):
        relative = path.relative_to(repo.root)
        if path.stat().st_size > MAX_SCAN_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        files.append(ScannedFile(path=path, relative_path=str(relative), text=text, lines=tuple(text.splitlines())))
    return files


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
) -> None:
    fact = Fact(predicate=predicate, subject_id=subject.entity_id, object_id=object_.entity_id, qualifier=qualifier or {})
    build.facts.append(fact)
    build.evidence.append(
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
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


def domain_entity(repo: RepoSnapshot, domain: str) -> Entity:
    return Entity(
        kind="Domain",
        identity={"tenant_id": TENANT_ID, "repo": repo.name, "name": domain.lower()},
        properties={},
    )


def env_var_entity(repo: RepoSnapshot, name: str) -> Entity:
    return Entity(
        kind="EnvVar",
        identity={"tenant_id": TENANT_ID, "repo": repo.name, "name": name},
        properties={},
    )


def endpoint_entity(repo: RepoSnapshot, method: str, path: str, host: str | None = None) -> Entity:
    return Entity(
        kind="Endpoint",
        identity={
            "tenant_id": TENANT_ID,
            "repo": repo.name,
            "protocol": "http",
            "method": method.upper() if method else "ANY",
            "path": normalize_endpoint_path(path),
            "host": host or None,
        },
        properties={},
    )


def event_channel_entity(repo: RepoSnapshot, name: str, broker_kind: str) -> Entity:
    return Entity(
        kind="EventChannel",
        identity={"tenant_id": TENANT_ID, "repo": repo.name, "broker_kind": broker_kind, "name": name},
        properties={},
    )


def deploy_target_entity(repo: RepoSnapshot, target_type: str, target: str) -> Entity:
    return Entity(
        kind="DeployTarget",
        identity={"tenant_id": TENANT_ID, "repo": repo.name, "type": target_type, "target": target},
        properties={},
    )


def normalize_endpoint_path(path: str) -> str:
    value = path.strip().strip("'\"`")
    if not value:
        return "/"
    if not value.startswith("/") and not value.startswith("http"):
        value = "/" + value
    return value
