from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
import json
import re
import subprocess
import tempfile

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import read_jsonl
from source.kg.core.tenant import DEFAULT_TENANT_ID, resolve_tenant_id
from source.kg.extraction.framework.allowlists import SUPPORTED_ENTITY_KINDS
from source.kg.languages import REGISTERED_LANGUAGES
from source.kg.languages.types import (
    ConsumerDependency,
    ConsumerManifestIssue,
    PackageMetadata,
    PackageResolver,
)


LINKER_SOURCE_SYSTEM = "package_linker"
LINKER_RULE_VERSION = "package-linker-1"
SNAPSHOT_ARTIFACT_BUILD_TYPES = frozenset(("fleet_relink", "multi_repo", "private_goldset_multi_repo"))
PACKAGE_CLASSIFICATIONS_FILENAME = "package_classifications.jsonl"
RELINK_PACKAGE_CLASSIFICATIONS_FILENAME = "cross_repo_package_classifications.jsonl"
RELINK_PACKAGE_COVERAGE_FILENAME = "cross_repo_package_coverage.jsonl"
RELINK_OUTPUT_FILES = frozenset(
    (
        "cross_repo_links.jsonl",
        "cross_repo_link_evidence.jsonl",
        RELINK_PACKAGE_CLASSIFICATIONS_FILENAME,
        RELINK_PACKAGE_COVERAGE_FILENAME,
        "manifest.json",
    )
)
STALE_SNAPSHOT_OUTPUT_FILES = frozenset(
    ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl", "metrics.jsonl", PACKAGE_CLASSIFICATIONS_FILENAME)
)
TENANT_SCOPED_ENTITY_KINDS = SUPPORTED_ENTITY_KINDS
_PACKAGE_RESOLVER_LANGUAGE_PRECEDENCE = ("python", "typescript", "dotnet")


@dataclass(frozen=True)
class RepoIdentity:
    tenant_id: str
    host: str
    owner: str
    name: str

    def to_json(self) -> JsonObject:
        return {"tenant_id": self.tenant_id, "host": self.host, "owner": self.owner, "name": self.name}


@dataclass(frozen=True)
class PackageProvider:
    repo: RepoSnapshot
    repo_identity: RepoIdentity
    package_name: str
    aliases: tuple[str, ...]
    manifest_path: Path | None
    resolver_language: str | None
    repo_entity_id: str
    service_entity_id: str | None


@dataclass(frozen=True)
class LinkerInput:
    repo: RepoSnapshot
    repo_identity: RepoIdentity
    entities: tuple[Entity, ...]
    validate_package_manifests: bool = False
    snapshot_dir: Path | None = None


@dataclass(frozen=True)
class LinkerResult:
    facts: tuple[Fact, ...]
    evidence: tuple[Evidence, ...]
    providers: tuple[PackageProvider, ...]
    ambiguous_package_count: int
    coverage: tuple[Coverage, ...] = ()
    consumer_dependencies: tuple[ConsumerDependency, ...] = ()
    consumer_manifest_issues: tuple[ConsumerManifestIssue, ...] = ()
    package_classifications: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class _RegisteredPackageResolver:
    language_name: str
    resolver: PackageResolver


@dataclass(frozen=True)
class _PackageMetadataSelection:
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None
    resolver_language: str | None


@dataclass(frozen=True)
class _ConsumerManifestCollection:
    dependencies: tuple[ConsumerDependency, ...]
    issues: tuple[ConsumerManifestIssue, ...]


def link_external_packages(inputs: list[LinkerInput] | tuple[LinkerInput, ...]) -> LinkerResult:
    consumer_manifests = _collect_consumer_manifest_results(inputs)
    providers = _package_providers(inputs)
    entity_repo_identities: dict[str, set[RepoIdentity]] = {}
    entities: list[Entity] = []
    for input_repo in inputs:
        entities.extend(input_repo.entities)
        for entity in input_repo.entities:
            if entity.kind == "ExternalPackage":
                entity_repo_identities.setdefault(entity.entity_id, set()).add(input_repo.repo_identity)

    link_facts, link_evidence, ambiguous_count = _link_external_packages(
        inputs,
        entities,
        providers,
        entity_repo_identities,
        consumer_manifests.dependencies,
    )
    classifications = _classify_external_packages(inputs, entities, providers, consumer_manifests.dependencies)
    coverage = _package_linkage_coverage(inputs, classifications, consumer_manifests.issues)
    return LinkerResult(
        facts=tuple(link_facts),
        evidence=tuple(link_evidence),
        coverage=coverage,
        providers=tuple(providers),
        ambiguous_package_count=ambiguous_count,
        consumer_dependencies=consumer_manifests.dependencies,
        consumer_manifest_issues=consumer_manifests.issues,
        package_classifications=classifications,
    )


def relink_snapshot_dirs(
    snapshot_dirs: list[str | Path] | tuple[str | Path, ...],
    output_dir: str | Path,
    *,
    tenant_id: str | None = None,
) -> JsonObject:
    inputs = tuple(_load_linker_input(Path(path), tenant_id=tenant_id) for path in snapshot_dirs)
    if not inputs:
        raise ValueError("relink requires at least one snapshot directory")
    _validate_unique_input_identities(inputs)
    out = Path(output_dir).expanduser().resolve()
    input_dirs = {input_repo.snapshot_dir for input_repo in inputs if input_repo.snapshot_dir is not None}
    if out in input_dirs:
        raise ValueError(f"relink output_dir must not be one of the input snapshot directories: {out}")

    result = link_external_packages(inputs)
    out.mkdir(parents=True, exist_ok=True)
    _validate_stale_snapshot_outputs(out)
    manifest: JsonObject = {
        "build_type": "fleet_relink",
        "built_at": utc_now_iso(),
        "tenant_id": inputs[0].repo_identity.tenant_id,
        "source_system": LINKER_SOURCE_SYSTEM,
        "rule_version": LINKER_RULE_VERSION,
        "repo_count": len(inputs),
        "repos": [
            {
                "repo_path": str(input_repo.repo.root),
                "repo_name": input_repo.repo.name,
                "owner": input_repo.repo.owner,
                "commit_sha": input_repo.repo.commit_sha,
            }
            for input_repo in inputs
        ],
        "repo_commit_sha_set": sorted({input_repo.repo.commit_sha for input_repo in inputs}),
        "repo_commit_fingerprints": [
            {
                "repo_identity": input_repo.repo_identity.to_json(),
                "commit_sha": input_repo.repo.commit_sha,
            }
            for input_repo in sorted(
                inputs,
                key=lambda value: (
                    value.repo_identity.tenant_id,
                    value.repo_identity.host,
                    value.repo_identity.owner,
                    value.repo_identity.name,
                    value.repo.commit_sha,
                ),
            )
        ],
        "provider_count": len(result.providers),
        "link_count": len(result.facts),
        "ambiguous_package_count": result.ambiguous_package_count,
        "consumer_dependency_count": len(result.consumer_dependencies),
        "consumer_manifest_issue_count": len(result.consumer_manifest_issues),
        "package_classification_count": len(result.package_classifications),
        "counts": {
            "facts": len({fact.fact_id for fact in result.facts}),
            "evidence": len({row.evidence_id for row in result.evidence}),
            "coverage": len({row.coverage_id for row in result.coverage}),
        },
    }
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as staging:
        staged = Path(staging)
        _write_jsonl(staged / "cross_repo_links.jsonl", (fact.to_record() for fact in result.facts), "fact_id")
        _write_jsonl(
            staged / "cross_repo_link_evidence.jsonl",
            (row.to_record() for row in result.evidence),
            "evidence_id",
        )
        _write_jsonl(
            staged / RELINK_PACKAGE_CLASSIFICATIONS_FILENAME,
            result.package_classifications,
            "classification_id",
        )
        _write_jsonl(
            staged / RELINK_PACKAGE_COVERAGE_FILENAME,
            (row.to_record() for row in result.coverage),
            "coverage_id",
        )
        _write_json_file(staged / "manifest.json", manifest)
        _publish_relink_outputs(out, staged)
    return manifest


def _validate_stale_snapshot_outputs(out: Path) -> None:
    for filename in (*RELINK_OUTPUT_FILES, *STALE_SNAPSHOT_OUTPUT_FILES):
        stale_path = out / filename
        if stale_path.exists() and not stale_path.is_file():
            raise ValueError(f"Cannot replace stale snapshot artifact because it is not a file: {stale_path}")


def _publish_relink_outputs(out: Path, staged: Path) -> None:
    filenames = (
        "cross_repo_links.jsonl",
        "cross_repo_link_evidence.jsonl",
        RELINK_PACKAGE_CLASSIFICATIONS_FILENAME,
        RELINK_PACKAGE_COVERAGE_FILENAME,
        "manifest.json",
    )
    backups: dict[str, Path] = {}
    published: list[str] = []
    try:
        for filename in (*filenames, *sorted(STALE_SNAPSHOT_OUTPUT_FILES)):
            target = out / filename
            backup = out / f".{filename}.bak"
            backup.unlink(missing_ok=True)
            if target.exists():
                target.replace(backup)
                backups[filename] = backup
        for filename in filenames:
            target = out / filename
            (staged / filename).replace(target)
            published.append(filename)
    except Exception:
        for filename in reversed(published):
            (out / filename).unlink(missing_ok=True)
        for filename, backup in backups.items():
            if backup.exists():
                backup.replace(out / filename)
        raise
    finally:
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def resolve_snapshot_dirs(paths: tuple[Path, ...], *, exclude_dirs: tuple[Path, ...] = ()) -> tuple[Path, ...]:
    snapshots: list[Path] = []
    excluded = {path.expanduser().resolve() for path in exclude_dirs}
    for path in paths:
        root = path.expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Snapshot directory does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Snapshot path must be a directory: {root}")
        root_manifest_kind = _classify_snapshot_manifest(root)
        if root_manifest_kind == "repo":
            snapshots.append(root)
            continue
        if root_manifest_kind == "invalid":
            raise ValueError(f"{root / 'manifest.json'}: manifest is not a valid repo snapshot")
        children = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.resolve() in excluded:
                continue
            manifest_kind = _classify_snapshot_manifest(child)
            if manifest_kind == "repo":
                children.append(child)
            elif manifest_kind == "invalid":
                raise ValueError(f"{child / 'manifest.json'}: manifest is not a valid repo snapshot")
        if not children:
            raise FileNotFoundError(f"No snapshot manifests found under: {root}")
        snapshots.extend(children)
    if not snapshots:
        raise ValueError("No snapshot directories provided")
    return tuple(dict.fromkeys(snapshots))


def default_output_dir(paths: tuple[Path, ...]) -> Path:
    if len(paths) == 1 and not _is_repo_snapshot_dir(paths[0].expanduser().resolve()):
        return paths[0].expanduser().resolve() / "_fleet"
    raise ValueError("--out is required unless --snapshot-dir points to a single fleet directory")


def _is_repo_snapshot_dir(path: Path) -> bool:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = _read_manifest_object(manifest_path)
    except ValueError:
        return False
    return _is_repo_snapshot_manifest(manifest)


def _classify_snapshot_manifest(path: Path) -> str | None:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = _read_manifest_object(manifest_path)
    build_type = manifest.get("build_type")
    if isinstance(build_type, str) and build_type in SNAPSHOT_ARTIFACT_BUILD_TYPES:
        return "artifact"
    if _is_repo_snapshot_manifest(manifest):
        return "repo"
    return "invalid"


def _read_manifest_object(path: Path) -> JsonObject:
    if not path.is_file():
        raise ValueError(f"{path} must be a JSON file")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return manifest


def _is_repo_snapshot_manifest(manifest: JsonObject) -> bool:
    if "build_type" in manifest:
        return False
    return (
        isinstance(manifest.get("repo_path"), str)
        and bool(manifest.get("repo_path"))
        and isinstance(manifest.get("commit_sha"), str)
        and bool(manifest.get("commit_sha"))
    )


def repo_identity(repo: RepoSnapshot, tenant_id: str) -> RepoIdentity:
    # Local builds do not preserve git forge host yet; owner/name still
    # prevents same-directory-name repos under different org roots from merging.
    return RepoIdentity(tenant_id=tenant_id, host="local", owner=repo.owner, name=repo.name)


def repo_identity_key(identity: RepoIdentity) -> str:
    return f"{identity.tenant_id}/{identity.host}/{identity.owner}/{identity.name}"


def repo_identity_evidence(evidence: list[Evidence], repo: RepoSnapshot, identity: RepoIdentity) -> list[Evidence]:
    rows: list[Evidence] = []
    for row in evidence:
        if row.bytes_ref is None:
            rows.append(row)
            continue
        bytes_ref = {
            **row.bytes_ref,
            "repo": repo_identity_key(identity),
            "repo_name": repo.name,
            "repo_identity": identity.to_json(),
        }
        rows.append(replace(row, bytes_ref=bytes_ref))
    return rows


def validate_unique_repo_identities(repos: list[RepoSnapshot], tenant_id: str) -> None:
    paths_by_identity: dict[RepoIdentity, list[str]] = {}
    for repo in repos:
        paths_by_identity.setdefault(repo_identity(repo, tenant_id), []).append(str(repo.root))
    duplicates = {identity: paths for identity, paths in paths_by_identity.items() if len(paths) > 1}
    if not duplicates:
        return
    details = "; ".join(
        f"{identity.tenant_id}/{identity.host}/{identity.owner}/{identity.name}: {paths}"
        for identity, paths in sorted(
            duplicates.items(),
            key=lambda item: (item[0].tenant_id, item[0].host, item[0].owner, item[0].name),
        )
    )
    raise ValueError(f"Multi-repo snapshots require unique repo identities. Duplicates: {details}")


def _validate_unique_input_identities(inputs: tuple[LinkerInput, ...]) -> None:
    tenant_ids = sorted({input_repo.repo_identity.tenant_id for input_repo in inputs})
    if len(tenant_ids) > 1:
        raise ValueError(f"Relink snapshots must belong to one tenant. Found tenants: {tenant_ids}")
    paths_by_identity: dict[RepoIdentity, list[str]] = {}
    for input_repo in inputs:
        paths_by_identity.setdefault(input_repo.repo_identity, []).append(str(input_repo.repo.root))
    duplicates = {identity: paths for identity, paths in paths_by_identity.items() if len(paths) > 1}
    if not duplicates:
        return
    details = "; ".join(
        f"{identity.tenant_id}/{identity.host}/{identity.owner}/{identity.name}: {paths}"
        for identity, paths in sorted(
            duplicates.items(),
            key=lambda item: (item[0].tenant_id, item[0].host, item[0].owner, item[0].name),
        )
    )
    raise ValueError(f"Relink snapshots require unique repo identities. Duplicates: {details}")


def _load_linker_input(snapshot_dir: Path, *, tenant_id: str | None) -> LinkerInput:
    root = snapshot_dir.expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Snapshot manifest does not exist: {manifest_path}")
    manifest = _read_manifest_object(manifest_path)
    repo_path = manifest.get("repo_path")
    commit_sha = manifest.get("commit_sha")
    if not isinstance(repo_path, str) or not repo_path:
        raise ValueError(f"{manifest_path}: repo_path must be a non-empty string")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise ValueError(f"{manifest_path}: commit_sha must be a non-empty string")

    repo_root = Path(repo_path).expanduser().resolve()
    if not repo_root.exists():
        raise FileNotFoundError(f"{manifest_path}: repo_path does not exist: {repo_root}")
    if not repo_root.is_dir():
        raise ValueError(f"{manifest_path}: repo_path must be a directory: {repo_root}")
    repo_name = _optional_manifest_string(manifest, "repo_name", repo_root.name, manifest_path)
    owner = _optional_manifest_string(manifest, "owner", repo_root.parent.name, manifest_path)
    repo = RepoSnapshot(
        repo_root,
        repo_name,
        owner,
        commit_sha,
        {},
    )
    _validate_repo_commit_matches_snapshot(repo)
    _validate_snapshot_package_manifests(repo_root, manifest, manifest_path)
    entities = tuple(
        _entity_from_record(row, root / "entities.jsonl")
        for row in _read_entity_rows(root / "entities.jsonl")
    )
    _validate_unique_entity_ids(entities, root / "entities.jsonl")
    resolved_tenant = _snapshot_tenant_id(manifest, tenant_id, entities)
    _validate_entity_tenants(entities, resolved_tenant, root / "entities.jsonl")
    return LinkerInput(
        repo=repo,
        repo_identity=repo_identity(repo, resolved_tenant),
        entities=entities,
        validate_package_manifests=True,
        snapshot_dir=root,
    )


def _optional_manifest_string(manifest: JsonObject, field: str, fallback: str, path: Path) -> str:
    if field not in manifest:
        return fallback
    value = manifest[field]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: {field} must be a non-empty string when present")
    return value


def _snapshot_tenant_id(manifest: JsonObject, tenant_id: str | None, entities: tuple[Entity, ...]) -> str:
    manifest_tenant = manifest.get("tenant_id")
    if "tenant_id" in manifest:
        if not isinstance(manifest_tenant, str) or not manifest_tenant.strip():
            raise ValueError("snapshot manifest tenant_id must be a non-empty string when present")
        resolved_manifest_tenant = resolve_tenant_id(manifest_tenant)
    else:
        entity_tenants = {
            value.strip()
            for entity in entities
            for value in (entity.identity.get("tenant_id"),)
            if isinstance(value, str) and value.strip()
        }
        if len(entity_tenants) > 1:
            raise ValueError(f"Snapshot entities contain multiple tenant_id values: {sorted(entity_tenants)}")
        resolved_manifest_tenant = next(iter(entity_tenants), DEFAULT_TENANT_ID)
    if tenant_id is not None:
        resolved_override = resolve_tenant_id(tenant_id)
        if resolved_override != resolved_manifest_tenant:
            raise ValueError(
                "relink tenant override must match snapshot tenant_id because entity IDs are tenant-scoped: "
                f"{resolved_override} != {resolved_manifest_tenant}"
            )
        return resolved_override
    return resolved_manifest_tenant


def _read_entity_rows(path: Path) -> tuple[JsonObject, ...]:
    if not path.is_file():
        raise ValueError(f"{path}: entities.jsonl must be a JSONL file")
    rows = read_jsonl(path)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
    return tuple(rows)


def _validate_snapshot_package_manifests(repo_root: Path, manifest: JsonObject, manifest_path: Path) -> None:
    raw_fingerprints = manifest.get("package_manifests")
    if raw_fingerprints is None:
        return
    if not isinstance(raw_fingerprints, list):
        raise ValueError(f"{manifest_path}: package_manifests must be a list when present")
    for index, raw_fingerprint in enumerate(raw_fingerprints):
        if not isinstance(raw_fingerprint, dict):
            raise ValueError(f"{manifest_path}: package_manifests[{index}] must be an object")
        relative_path = raw_fingerprint.get("path")
        expected_sha256 = raw_fingerprint.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError(f"{manifest_path}: package_manifests[{index}].path must be a non-empty string")
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ValueError(f"{manifest_path}: package_manifests[{index}].path must stay inside repo_path")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise ValueError(f"{manifest_path}: package_manifests[{index}].sha256 must be a non-empty string")
        package_manifest = repo_root / relative_path
        if not package_manifest.is_file():
            raise ValueError(f"Package manifest recorded in snapshot is not a file: {package_manifest}")
        actual_sha256 = sha256(package_manifest.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                "Package manifest content differs from snapshot manifest fingerprint: "
                f"{package_manifest}"
            )


def _entity_from_record(row: JsonObject, path: Path) -> Entity:
    kind = row.get("kind")
    identity = row.get("identity")
    properties = row.get("properties", {})
    canonical_status = row.get("canonical_status", "canonical")
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"{path}: entity kind must be a non-empty string")
    if not isinstance(identity, dict):
        raise ValueError(f"{path}: entity identity must be an object")
    if not isinstance(properties, dict):
        raise ValueError(f"{path}: entity properties must be an object")
    if not isinstance(canonical_status, str) or canonical_status not in {"canonical", "candidate", "demoted"}:
        raise ValueError(f"{path}: entity canonical_status is unsupported: {canonical_status}")
    category = properties.get("category")
    if kind == "ExternalPackage" and category is not None and not isinstance(category, str):
        raise ValueError(f"{path}: ExternalPackage category must be a string when present")
    entity = Entity(kind, identity, properties, canonical_status=canonical_status)
    expected_id = row.get("entity_id")
    if not isinstance(expected_id, str) or not expected_id:
        raise ValueError(f"{path}: entity_id must be a non-empty string")
    if expected_id != entity.entity_id:
        raise ValueError(f"{path}: entity_id does not match kind and identity: {expected_id}")
    return entity


def _validate_unique_entity_ids(entities: tuple[Entity, ...], path: Path) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for entity in entities:
        if entity.entity_id in seen:
            duplicates.add(entity.entity_id)
        seen.add(entity.entity_id)
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"{path}: duplicate entity_id values: {duplicate_list}")


def _validate_entity_tenants(entities: tuple[Entity, ...], tenant_id: str, path: Path) -> None:
    mismatches: list[str] = []
    for entity in entities:
        entity_tenant = entity.identity.get("tenant_id")
        if entity.kind in TENANT_SCOPED_ENTITY_KINDS and (
            not isinstance(entity_tenant, str) or not entity_tenant
        ):
            raise ValueError(f"{path}: entity tenant_id must be a non-empty string")
        if isinstance(entity_tenant, str) and entity_tenant != tenant_id:
            mismatches.append(f"{entity.kind}:{entity.entity_id}:{entity_tenant}")
    if mismatches:
        raise ValueError(f"{path}: entity tenant_id values do not match snapshot tenant_id {tenant_id}: {mismatches}")


def _write_jsonl(path: Path, records: Iterable[JsonObject], key: str) -> None:
    seen: set[str] = set()
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                record_key = str(record[key])
                if record_key in seen:
                    raise ValueError(f"{path}: duplicate {key}: {record_key}")
                seen.add(record_key)
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_json_file(path: Path, record: JsonObject) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _package_providers(inputs: list[LinkerInput] | tuple[LinkerInput, ...]) -> list[PackageProvider]:
    providers: list[PackageProvider] = []
    for input_repo in inputs:
        repo = input_repo.repo
        entities = list(input_repo.entities)
        repo_entity = _select_repo_entity(entities, input_repo.repo_identity)
        if repo_entity is None:
            if input_repo.validate_package_manifests:
                raise ValueError(
                    "Snapshot manifest repo identity does not match a Repo entity in entities.jsonl: "
                    f"{repo_identity_key(input_repo.repo_identity)}"
                )
            continue
        service_entities = [entity for entity in entities if entity.kind == "Service"]
        package_selection = _package_metadata_selection(
            repo,
            validate_snapshot_manifest=input_repo.validate_package_manifests,
        )
        service_entity = _select_service_entity(service_entities, package_selection.aliases)
        providers.append(
            PackageProvider(
                repo=repo,
                repo_identity=input_repo.repo_identity,
                package_name=package_selection.package_name,
                aliases=tuple(sorted({alias for alias in package_selection.aliases if alias})),
                manifest_path=package_selection.manifest_path,
                resolver_language=package_selection.resolver_language,
                repo_entity_id=repo_entity.entity_id,
                service_entity_id=service_entity.entity_id if service_entity else None,
            )
        )
    return providers


def _select_repo_entity(entities: list[Entity], identity: RepoIdentity) -> Entity | None:
    matches_by_id = {
        entity.entity_id: entity
        for entity in entities
        if entity.kind == "Repo"
        and entity.identity.get("tenant_id") == identity.tenant_id
        and entity.identity.get("host") == identity.host
        and entity.identity.get("owner") == identity.owner
        and entity.identity.get("name") == identity.name
    }
    matches = list(matches_by_id.values())
    return matches[0] if len(matches) == 1 else None


def _select_service_entity(services: list[Entity], aliases: Iterable[str]) -> Entity | None:
    services_by_id = {service.entity_id: service for service in services}
    unique_services = list(services_by_id.values())
    if len(unique_services) == 1:
        return unique_services[0]

    normalized_aliases = {_normalize_package_name(alias) for alias in aliases}
    matches = [
        service
        for service in unique_services
        if _normalize_package_name(str(service.identity.get("slug", ""))) in normalized_aliases
    ]
    return matches[0] if len(matches) == 1 else None


def _package_metadata(repo: RepoSnapshot, *, validate_snapshot_manifest: bool) -> tuple[str, set[str], Path | None]:
    selection = _package_metadata_selection(repo, validate_snapshot_manifest=validate_snapshot_manifest)
    return selection.package_name, set(selection.aliases), selection.manifest_path


def _package_metadata_selection(
    repo: RepoSnapshot,
    *,
    validate_snapshot_manifest: bool,
) -> _PackageMetadataSelection:
    for registered in _package_resolvers_in_precedence_order():
        metadata = _resolver_package_metadata(
            repo,
            registered,
            validate_snapshot_manifest=validate_snapshot_manifest,
        )
        if metadata is None:
            continue
        return _PackageMetadataSelection(
            metadata.package_name,
            frozenset(metadata.aliases),
            metadata.manifest_path,
            registered.language_name,
        )
    if validate_snapshot_manifest:
        _validate_repo_commit_matches_snapshot(repo)
    return _PackageMetadataSelection(repo.name, frozenset((repo.name,)), None, None)


def _resolver_package_metadata(
    repo: RepoSnapshot,
    registered: _RegisteredPackageResolver,
    *,
    validate_snapshot_manifest: bool,
) -> PackageMetadata | None:
    resolver = registered.resolver
    manifest_paths = tuple(resolver.manifest_paths(repo))
    manifest_path_set = set(manifest_paths)
    candidate_paths = _ordered_unique_paths(
        (*_resolver_manifest_candidate_paths(repo, resolver), *manifest_paths)
    )
    for candidate in candidate_paths:
        if candidate in manifest_path_set:
            _validate_package_manifest_file(candidate)
            if validate_snapshot_manifest:
                _validate_manifest_file_matches_snapshot(repo, candidate)
            continue
        if validate_snapshot_manifest:
            _validate_manifest_file_matches_snapshot(repo, candidate)
    if manifest_path_set:
        return resolver.package_metadata(repo)
    return None


def _resolver_manifest_candidate_paths(repo: RepoSnapshot, resolver: PackageResolver) -> tuple[Path, ...]:
    raw_filenames = getattr(resolver, "manifest_filenames", ())
    if not isinstance(raw_filenames, tuple) or not all(isinstance(filename, str) for filename in raw_filenames):
        raise ValueError(f"{type(resolver).__name__}.manifest_filenames must be tuple[str, ...] when present")
    return tuple(repo.root / filename for filename in raw_filenames)


def _ordered_unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(paths))


def _package_resolvers_in_precedence_order() -> tuple[_RegisteredPackageResolver, ...]:
    languages_by_name = {language.name: language for language in REGISTERED_LANGUAGES}
    ordered_languages = []
    for language_name in _PACKAGE_RESOLVER_LANGUAGE_PRECEDENCE:
        language = languages_by_name.pop(language_name, None)
        if language is not None:
            ordered_languages.append(language)
    ordered_languages.extend(language for language in REGISTERED_LANGUAGES if language.name in languages_by_name)

    resolvers: list[_RegisteredPackageResolver] = []
    for language in ordered_languages:
        resolver = language.package_resolver()
        if resolver is None:
            continue
        resolvers.append(_RegisteredPackageResolver(language.name, resolver))
    return tuple(resolvers)


def _collect_consumer_manifest_results(
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
) -> _ConsumerManifestCollection:
    dependencies: list[ConsumerDependency] = []
    issues: list[ConsumerManifestIssue] = []
    for input_repo in inputs:
        # PR-2 collects manifest evidence in memory for PR-1 classification.
        # Relink snapshots do not yet persist per-repo language dimensions, so
        # extractors fail closed on absent manifests; persisted dependency JSONL
        # and coverage rows land with the classifier.
        for language in REGISTERED_LANGUAGES:
            extractor = language.consumer_manifest_extractor()
            if extractor is None:
                continue
            result = extractor.extract(input_repo.repo)
            dependencies.extend(result.dependencies)
            issues.extend(result.issues)
    return _ConsumerManifestCollection(tuple(dependencies), tuple(issues))


def _classify_external_packages(
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
    entities: list[Entity],
    providers: list[PackageProvider],
    consumer_dependencies: tuple[ConsumerDependency, ...],
) -> tuple[JsonObject, ...]:
    provider_index: dict[str, set[RepoIdentity]] = {}
    for provider in providers:
        for alias in provider.aliases:
            provider_index.setdefault(_normalize_package_name(alias), set()).add(provider.repo_identity)
        provider_index.setdefault(_normalize_package_name(provider.package_name), set()).add(provider.repo_identity)

    dependencies_by_consumer = _consumer_dependencies_by_repo(inputs, consumer_dependencies)
    providers_by_identity = _providers_by_identity(providers)
    classifications: list[JsonObject] = []
    for entity in entities:
        if entity.kind != "ExternalPackage":
            continue
        consumer_identity = _external_package_repo_identity(entity, inputs)
        candidate_names = _external_package_candidate_names(entity)
        matching_dependencies = _matching_consumer_dependencies(
            candidate_names,
            dependencies_by_consumer.get(consumer_identity, ()),
        )
        dependency = matching_dependencies[0] if len(matching_dependencies) == 1 else None
        bucket = "unknown"
        reason = "code import has no matching consumer manifest dependency"
        manifest_path = None
        line_number = None
        if _is_builtin_package(entity):
            bucket = "builtin_or_stdlib"
            reason = "extractor classified package as builtin or stdlib"
        elif len(matching_dependencies) > 1:
            bucket = "unknown"
            reason = "multiple consumer manifest dependencies match the imported package"
        elif dependency is not None:
            manifest_path = str(dependency.manifest_path)
            line_number = dependency.line_number
            target_match = _manifest_target_repo_identity(dependency, consumer_identity, inputs)
            provider_matches = {
                identity
                for name in {dependency.declared_name, *candidate_names}
                for identity in provider_index.get(_normalize_package_name(name), set())
                if identity != consumer_identity
            }
            if (
                target_match is not None
                and target_match != consumer_identity
                and len(providers_by_identity.get(target_match, ())) == 1
            ):
                provider_matches.add(target_match)
            if len(provider_matches) == 1:
                bucket = "candidate_internal"
                if target_match is not None:
                    reason = "consumer manifest dependency target matches exactly one fleet repo"
                else:
                    reason = "consumer manifest dependency matches exactly one fleet provider"
            elif len(provider_matches) > 1:
                bucket = "candidate_internal_ambiguous"
                reason = "consumer manifest dependency matches multiple fleet providers"
            elif dependency.spec_form in {"workspace", "file_path", "git_url"}:
                bucket = "consumer_manifest_external"
                reason = "path, workspace, or git dependency has no matching fleet provider; treating as out-of-fleet"
            elif dependency.spec_form == "registry":
                bucket = "consumer_manifest_external"
                reason = "registry dependency has no matching fleet provider"
            else:
                bucket = "unknown"
                reason = "consumer manifest dependency has unknown spec form"
        package_name = _non_empty_string(entity.identity.get("name")) or next(iter(sorted(candidate_names)), "")
        classification_id = _package_classification_id(entity, consumer_identity, bucket)
        classifications.append(
            {
                "classification_id": classification_id,
                "entity_id": entity.entity_id,
                "repo_identity": consumer_identity.to_json() if consumer_identity is not None else None,
                "package_name": package_name,
                "bucket": bucket,
                "reason": reason,
                "manifest_path": manifest_path,
                "line_number": line_number,
                "language": _language_from_manifest_path(Path(manifest_path)) if manifest_path else None,
            }
        )
    return _dedupe_package_classifications(classifications)


def _dedupe_package_classifications(classifications: list[JsonObject]) -> tuple[JsonObject, ...]:
    rows_by_id: dict[str, JsonObject] = {}
    for row in classifications:
        classification_id = str(row["classification_id"])
        previous = rows_by_id.get(classification_id)
        if previous is None:
            rows_by_id[classification_id] = row
        elif previous != row:
            raise ValueError(f"Conflicting package classification rows for classification_id: {classification_id}")
    return tuple(rows_by_id.values())


def _package_linkage_coverage(
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
    classifications: tuple[JsonObject, ...],
    manifest_issues: tuple[ConsumerManifestIssue, ...],
) -> tuple[Coverage, ...]:
    rows: list[Coverage] = []
    for row in classifications:
        reason = _coverage_reason_for_classification(row)
        if reason is None:
            continue
        repo_identity_value = row.get("repo_identity")
        repo_identity_obj = repo_identity_value if isinstance(repo_identity_value, dict) else {}
        tenant_id = _non_empty_string(repo_identity_obj.get("tenant_id")) or DEFAULT_TENANT_ID
        scope_ref: JsonObject = {
            "repo": _non_empty_string(repo_identity_obj.get("name")) or "-",
            "repo_owner": _non_empty_string(repo_identity_obj.get("owner")),
            "repo_identity": dict(repo_identity_obj),
            "language": _non_empty_string(row.get("language")),
            "reason": reason,
            "package_name": _non_empty_string(row.get("package_name")) or "-",
            "classifier_bucket": _non_empty_string(row.get("bucket")) or "-",
        }
        manifest_path = _non_empty_string(row.get("manifest_path"))
        if manifest_path is not None:
            scope_ref["manifest_path"] = _display_manifest_path(Path(manifest_path), inputs)
        line_number = row.get("line_number")
        if isinstance(line_number, int) and not isinstance(line_number, bool) and line_number > 0:
            scope_ref["line_number"] = line_number
        rows.append(
            Coverage(
                tenant_id=tenant_id,
                predicate="RESOLVES_TO_REPO",
                scope_ref=scope_ref,
                state="partially_instrumented",
                source_system=LINKER_SOURCE_SYSTEM,
            )
        )
    for issue in manifest_issues:
        consumer_identity = _consumer_identity_for_path(issue.manifest_path, inputs)
        if consumer_identity is None:
            continue
        rows.append(
            Coverage(
                tenant_id=consumer_identity.tenant_id,
                predicate="RESOLVES_TO_REPO",
                scope_ref={
                    "repo": consumer_identity.name,
                    "repo_owner": consumer_identity.owner,
                    "repo_identity": consumer_identity.to_json(),
                    "language": issue.language,
                    "reason": issue.reason,
                    "package_name": "-",
                    "classifier_bucket": "manifest_unreadable",
                    "manifest_path": _display_manifest_path(issue.manifest_path, inputs),
                    "message": issue.message,
                },
                state="partially_instrumented",
                source_system=LINKER_SOURCE_SYSTEM,
            )
        )
    return tuple(_dedupe_coverage(rows))


def _coverage_reason_for_classification(row: JsonObject) -> str | None:
    bucket = row.get("bucket")
    reason = row.get("reason")
    if bucket == "candidate_internal_ambiguous":
        return "cross_repo_dependency_ambiguous_provider"
    if bucket == "unknown":
        return "cross_repo_dependency_unknown_category"
    if bucket == "consumer_manifest_external" and isinstance(reason, str) and reason.startswith(
        "path, workspace, or git dependency"
    ):
        return "cross_repo_dependency_no_provider"
    return None


def _dedupe_coverage(rows: list[Coverage]) -> tuple[Coverage, ...]:
    rows_by_id: dict[str, Coverage] = {}
    for row in rows:
        previous = rows_by_id.get(row.coverage_id)
        if previous is not None and previous != row:
            raise ValueError(f"Conflicting coverage rows for coverage_id: {row.coverage_id}")
        rows_by_id[row.coverage_id] = row
    return tuple(rows_by_id.values())


def _consumer_identity_for_path(
    path: Path,
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
) -> RepoIdentity | None:
    matches: list[RepoIdentity] = []
    resolved = path.resolve(strict=False)
    for input_repo in inputs:
        try:
            resolved.relative_to(input_repo.repo.root.resolve(strict=False))
        except ValueError:
            continue
        matches.append(input_repo.repo_identity)
    return matches[0] if len(matches) == 1 else None


def _display_manifest_path(path: Path, inputs: list[LinkerInput] | tuple[LinkerInput, ...]) -> str:
    resolved = path.resolve(strict=False)
    for input_repo in inputs:
        try:
            return str(resolved.relative_to(input_repo.repo.root.resolve(strict=False)))
        except ValueError:
            continue
    return str(path)


def _language_from_manifest_path(path: Path) -> str | None:
    if path.name in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return "typescript"
    if path.name in {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"}:
        return "python"
    if path.suffix == ".csproj":
        return "dotnet"
    return None


def write_package_classifications(output_dir: str | Path, records: tuple[JsonObject, ...]) -> None:
    _write_jsonl(Path(output_dir).expanduser().resolve() / PACKAGE_CLASSIFICATIONS_FILENAME, records, "classification_id")


def _consumer_dependencies_by_repo(
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
    dependencies: tuple[ConsumerDependency, ...],
) -> dict[RepoIdentity, tuple[ConsumerDependency, ...]]:
    grouped: dict[RepoIdentity, list[ConsumerDependency]] = {}
    for dependency in dependencies:
        for input_repo in inputs:
            try:
                dependency.manifest_path.resolve().relative_to(input_repo.repo.root.resolve())
            except ValueError:
                continue
            grouped.setdefault(input_repo.repo_identity, []).append(dependency)
            break
    return {identity: tuple(rows) for identity, rows in grouped.items()}


def _matching_consumer_dependencies(
    candidate_names: set[str],
    dependencies: tuple[ConsumerDependency, ...],
) -> tuple[ConsumerDependency, ...]:
    normalized_candidates = {_normalize_package_name(name) for name in candidate_names}
    return tuple(
        dependency
        for dependency in dependencies
        if _normalize_package_name(dependency.declared_name) in normalized_candidates
    )


def _providers_by_identity(providers: list[PackageProvider]) -> dict[RepoIdentity, tuple[PackageProvider, ...]]:
    grouped: dict[RepoIdentity, list[PackageProvider]] = {}
    for provider in providers:
        grouped.setdefault(provider.repo_identity, []).append(provider)
    return {identity: tuple(rows) for identity, rows in grouped.items()}


def _manifest_target_provider_match(
    candidate_names: set[str],
    dependencies: tuple[ConsumerDependency, ...],
    consumer_identity: RepoIdentity,
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
    providers_by_identity: dict[RepoIdentity, tuple[PackageProvider, ...]],
) -> tuple[ConsumerDependency | None, PackageProvider | None]:
    matches: list[tuple[ConsumerDependency, PackageProvider]] = []
    for dependency in _matching_consumer_dependencies(candidate_names, dependencies):
        target_identity = _manifest_target_repo_identity(dependency, consumer_identity, inputs)
        if target_identity is None or target_identity == consumer_identity:
            continue
        target_providers = providers_by_identity.get(target_identity, ())
        if len(target_providers) == 1:
            matches.append((dependency, target_providers[0]))
    return matches[0] if len(matches) == 1 else (None, None)


def _manifest_target_repo_identity(
    dependency: ConsumerDependency,
    consumer_identity: RepoIdentity | None,
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
) -> RepoIdentity | None:
    if consumer_identity is None or dependency.target_url is None:
        return None
    if dependency.spec_form == "git_url":
        from source.kg.build.repo_identity import normalize_git_url

        target = normalize_git_url(dependency.target_url)
        if target is None:
            return None
        matches = [
            input_repo.repo_identity
            for input_repo in inputs
            if input_repo.repo_identity.tenant_id == consumer_identity.tenant_id
            and input_repo.repo_identity.owner == target.owner
            and input_repo.repo_identity.name == target.name
            and (input_repo.repo_identity.host == target.host or input_repo.repo_identity.host == "local")
        ]
        return matches[0] if len(matches) == 1 else None
    if dependency.spec_form == "file_path":
        from source.kg.build.repo_identity import resolve_file_path

        target_repo = resolve_file_path(
            dependency.target_url,
            dependency.manifest_path,
            tuple(input_repo.repo for input_repo in inputs),
        )
        if target_repo is None:
            return None
        matches = [
            input_repo.repo_identity
            for input_repo in inputs
            if input_repo.repo.root.resolve(strict=False) == target_repo.root.resolve(strict=False)
            and input_repo.repo_identity.tenant_id == consumer_identity.tenant_id
        ]
        return matches[0] if len(matches) == 1 else None
    return None


def _external_package_repo_identity(
    package: Entity,
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
) -> RepoIdentity | None:
    repo_name = package.identity.get("repo")
    tenant_id = package.identity.get("tenant_id")
    matches = [
        input_repo.repo_identity
        for input_repo in inputs
        if input_repo.repo_identity.name == repo_name and input_repo.repo_identity.tenant_id == tenant_id
    ]
    return matches[0] if len(matches) == 1 else None


def _package_classification_id(entity: Entity, consumer_identity: RepoIdentity | None, bucket: str) -> str:
    identity_key = (
        repo_identity_key(consumer_identity)
        if consumer_identity is not None
        else json.dumps(entity.identity, sort_keys=True)
    )
    digest = sha256(f"{entity.entity_id}\0{identity_key}\0{bucket}".encode("utf-8")).hexdigest()[:16]
    return f"pkgclass:{digest}"


def _validate_package_manifest_file(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"Package manifest path is not a file: {path}")


def _validate_manifest_file_matches_snapshot(repo: RepoSnapshot, manifest_path: Path) -> None:
    _validate_repo_commit_matches_snapshot(repo)
    if repo.commit_sha == "working-tree":
        return
    status = _git_status_porcelain(repo.root, manifest_path)
    if status:
        relative = manifest_path.relative_to(repo.root)
        raise ValueError(f"Package manifest has uncommitted changes relative to snapshot commit: {relative}")


def _validate_repo_commit_matches_snapshot(repo: RepoSnapshot) -> None:
    if repo.commit_sha == "working-tree":
        return
    current_commit = _git_commit_sha(repo.root)
    if current_commit != repo.commit_sha:
        raise ValueError(
            f"Snapshot commit {repo.commit_sha} does not match current repo commit {current_commit}: {repo.root}"
        )


def _git_commit_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required to validate snapshot commit before relink") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"Repo path is not a git working copy, cannot validate snapshot commit: {root}") from exc
    return result.stdout.strip() or "working-tree"


def _git_status_porcelain(root: Path, path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--ignored", "--", str(path.relative_to(root))],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required to validate package manifest cleanliness before relink") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"git status failed while validating package manifest: {path}") from exc
    return result.stdout.strip()


def _link_external_packages(
    inputs: list[LinkerInput] | tuple[LinkerInput, ...],
    entities: list[Entity],
    providers: list[PackageProvider],
    entity_repo_identities: dict[str, set[RepoIdentity]],
    consumer_dependencies: tuple[ConsumerDependency, ...],
) -> tuple[list[Fact], list[Evidence], int]:
    provider_index: dict[str, list[PackageProvider]] = {}
    for provider in providers:
        for alias in provider.aliases:
            provider_index.setdefault(_normalize_package_name(alias), []).append(provider)

    facts: list[Fact] = []
    evidence: list[Evidence] = []
    ambiguous_count = 0
    registered_resolvers = _package_resolvers_in_precedence_order()
    dependencies_by_consumer = _consumer_dependencies_by_repo(inputs, consumer_dependencies)
    providers_by_identity = _providers_by_identity(providers)
    packages_by_id: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.kind == "ExternalPackage":
            packages_by_id.setdefault(entity.entity_id, []).append(entity)
    for package_group in packages_by_id.values():
        if any(_is_builtin_package(package) for package in package_group):
            continue
        package = package_group[0]
        consumer_identities = entity_repo_identities.get(package.entity_id, set())
        if not consumer_identities:
            raise ValueError(
                "ExternalPackage entity missing repo identity tracking: "
                f"entity_id={package.entity_id}, identity={package.identity}"
            )
        candidate_names = _external_package_candidate_names(package)
        matches_by_consumer: dict[RepoIdentity, set[PackageProvider]] = {}
        manifest_target_dependencies: dict[RepoIdentity, ConsumerDependency] = {}
        group_ambiguous = False
        for consumer_identity in _sort_repo_identities(consumer_identities):
            target_dependency, target_provider = _manifest_target_provider_match(
                candidate_names,
                dependencies_by_consumer.get(consumer_identity, ()),
                consumer_identity,
                inputs,
                providers_by_identity,
            )
            if target_provider is not None:
                consumer_matches = {target_provider}
                manifest_target_dependencies[consumer_identity] = target_dependency
            else:
                consumer_matches = {
                    provider
                    for name in candidate_names
                    for provider in provider_index.get(_normalize_package_name(name), [])
                    if provider.repo_identity != consumer_identity
                }
                for registered_resolver in registered_resolvers:
                    if consumer_matches:
                        break
                    consumer_matches = _resolver_matches(
                        candidate_names,
                        providers,
                        consumer_identity,
                        registered_resolver,
                    )
            if not consumer_matches:
                continue
            if len(consumer_matches) > 1:
                group_ambiguous = True
                continue
            matches_by_consumer[consumer_identity] = consumer_matches
        if group_ambiguous:
            ambiguous_count += 1
            continue
        if not matches_by_consumer or len(matches_by_consumer) != len(consumer_identities):
            continue
        matched_providers = {provider for matches in matches_by_consumer.values() for provider in matches}
        if len(matched_providers) > 1:
            ambiguous_count += 1
            continue
        provider = next(iter(matched_providers))
        matched_name = _matched_name(candidate_names, provider)
        link_consumer_identities = set(matches_by_consumer)
        target_dependencies = tuple(
            dependency
            for identity in _sort_repo_identities(link_consumer_identities)
            for dependency in (manifest_target_dependencies.get(identity),)
            if dependency is not None
        )
        target_dependency = target_dependencies[0] if len(target_dependencies) == 1 else None
        link_rule = (
            "manifest_target_repo_match"
            if target_dependencies and len(target_dependencies) == len(link_consumer_identities)
            else "unique_normalized_package_name_match"
        )
        package_facts = [
            Fact(
                predicate="RESOLVES_TO_REPO",
                subject_id=package.entity_id,
                object_id=provider.repo_entity_id,
                qualifier=_link_qualifier(
                    package,
                    provider,
                    matched_name,
                    link_consumer_identities,
                    rule=link_rule,
                    dependency=target_dependency,
                    dependency_count=len(target_dependencies),
                ),
            )
        ]
        if provider.service_entity_id is not None and target_dependency is None:
            package_facts.append(
                Fact(
                    predicate="RESOLVES_TO_SERVICE",
                    subject_id=package.entity_id,
                    object_id=provider.service_entity_id,
                    qualifier=_link_qualifier(
                        package,
                        provider,
                        matched_name,
                        link_consumer_identities,
                        rule=link_rule,
                        dependency=target_dependency,
                        dependency_count=len(target_dependencies),
                    ),
                )
            )
        facts.extend(package_facts)
        evidence.extend(
            _link_evidence(
                package,
                provider,
                package_facts,
                link_consumer_identities,
                rule=link_rule,
                dependency=target_dependency,
                dependencies_by_consumer=manifest_target_dependencies if link_rule == "manifest_target_repo_match" else {},
            )
        )
    return facts, evidence, ambiguous_count


def _resolver_matches(
    candidate_names: set[str],
    providers: list[PackageProvider],
    consumer_identity: RepoIdentity,
    registered: _RegisteredPackageResolver,
) -> set[PackageProvider]:
    resolver_providers = [
        provider
        for provider in providers
        if provider.repo_identity != consumer_identity and provider.resolver_language == registered.language_name
    ]
    if not resolver_providers:
        return set()
    matches: set[PackageProvider] = set()
    target_repos = tuple(provider.repo for provider in resolver_providers)
    for name in candidate_names:
        resolved_name = registered.resolver.resolve(name, target_repos)
        if resolved_name is None:
            continue
        normalized_resolved = _normalize_package_name(resolved_name)
        matches.update(
            provider
            for provider in resolver_providers
            if _normalize_package_name(provider.package_name) == normalized_resolved
        )
    return matches if len(matches) == 1 else set()


def _external_package_candidate_names(package: Entity) -> set[str]:
    properties = package.properties
    identity = package.identity
    return {
        value
        for value in (
            _non_empty_string(identity.get("name")),
            _non_empty_string(properties.get("import_root")),
            _non_empty_string(properties.get("distribution_name")),
        )
        if value is not None
    }


def _is_builtin_package(package: Entity) -> bool:
    category = package.properties.get("category")
    return isinstance(category, str) and category in {"stdlib", "node_builtin"}


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _matched_name(candidate_names: set[str], provider: PackageProvider) -> str:
    provider_names = {_normalize_package_name(alias): alias for alias in provider.aliases}
    for name in sorted(candidate_names):
        if _normalize_package_name(name) in provider_names:
            return name
    return sorted(candidate_names)[0]


def _link_qualifier(
    package: Entity,
    provider: PackageProvider,
    matched_name: str,
    consumer_identities: set[RepoIdentity],
    *,
    rule: str,
    dependency: ConsumerDependency | None,
    dependency_count: int,
) -> JsonObject:
    qualifier: JsonObject = {
        "rule": rule,
        "rule_version": LINKER_RULE_VERSION,
        "consumer_repo": package.identity.get("repo"),
        "package_name": package.identity.get("name"),
        "matched_name": matched_name,
        "provider_repo": provider.repo.name,
        "provider_repo_identity": provider.repo_identity.to_json(),
        "provider_package_name": provider.package_name,
    }
    qualifier.update(_consumer_identity_ref(consumer_identities))
    if dependency is not None:
        qualifier.update(
            {
                "dependency_name": dependency.declared_name,
                "dependency_spec_form": dependency.spec_form,
                "dependency_target_url": dependency.target_url,
            }
        )
    elif dependency_count:
        qualifier["dependency_count"] = dependency_count
    return qualifier


def _link_evidence(
    package: Entity,
    provider: PackageProvider,
    facts: list[Fact],
    consumer_identities: set[RepoIdentity],
    *,
    rule: str,
    dependency: ConsumerDependency | None,
    dependencies_by_consumer: dict[RepoIdentity, ConsumerDependency],
) -> list[Evidence]:
    rows: list[Evidence] = []
    for fact in facts:
        if dependency is None and dependencies_by_consumer:
            for consumer_identity, consumer_dependency in sorted(
                dependencies_by_consumer.items(),
                key=lambda item: (item[0].tenant_id, item[0].host, item[0].owner, item[0].name),
            ):
                if consumer_identity not in consumer_identities:
                    continue
                rows.append(
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system=LINKER_SOURCE_SYSTEM,
                        source_ref={
                            "rule": rule,
                            "rule_version": LINKER_RULE_VERSION,
                            "consumer_repo": consumer_identity.name,
                            "consumer_repo_identity": consumer_identity.to_json(),
                            "provider_repo": provider.repo.name,
                            "provider_repo_identity": provider.repo_identity.to_json(),
                            "provider_package_name": provider.package_name,
                            **_dependency_source_ref(consumer_dependency),
                        },
                        bytes_ref=_dependency_bytes_ref(consumer_dependency, {consumer_identity}),
                        confidence=1.0,
                    )
                )
            continue
        rows.append(
            Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
            source_system=LINKER_SOURCE_SYSTEM,
            source_ref={
                "rule": rule,
                "rule_version": LINKER_RULE_VERSION,
                "consumer_repo": package.identity.get("repo"),
                **_consumer_identity_ref(consumer_identities),
                "provider_repo": provider.repo.name,
                "provider_repo_identity": provider.repo_identity.to_json(),
                "provider_package_name": provider.package_name,
                **_dependency_source_ref(dependency),
            },
            bytes_ref=_dependency_bytes_ref(dependency, consumer_identities) or _manifest_bytes_ref(provider),
            confidence=1.0,
        )
        )
    return rows


def _consumer_identity_ref(consumer_identities: set[RepoIdentity]) -> JsonObject:
    if len(consumer_identities) == 1:
        return {"consumer_repo_identity": next(iter(consumer_identities)).to_json()}
    if len(consumer_identities) > 1:
        return {
            "consumer_repo_identities": [
                identity.to_json()
                for identity in _sort_repo_identities(consumer_identities)
            ]
        }
    return {}


def _dependency_source_ref(dependency: ConsumerDependency | None) -> JsonObject:
    if dependency is None:
        return {}
    return {
        "dependency_name": dependency.declared_name,
        "dependency_spec_form": dependency.spec_form,
        "dependency_target_url": dependency.target_url,
    }


def _sort_repo_identities(identities: set[RepoIdentity]) -> list[RepoIdentity]:
    return sorted(identities, key=lambda value: (value.tenant_id, value.host, value.owner, value.name))


def _manifest_bytes_ref(provider: PackageProvider) -> JsonObject | None:
    if provider.manifest_path is None or not provider.manifest_path.exists():
        return None
    return {
        "repo": repo_identity_key(provider.repo_identity),
        "repo_name": provider.repo.name,
        "repo_identity": provider.repo_identity.to_json(),
        "commit_sha": provider.repo.commit_sha,
        "path": str(provider.manifest_path.relative_to(provider.repo.root)),
        "line_start": 1,
        "line_end": 1,
    }


def _dependency_bytes_ref(
    dependency: ConsumerDependency | None,
    consumer_identities: set[RepoIdentity],
) -> JsonObject | None:
    if dependency is None or not dependency.manifest_path.exists() or len(consumer_identities) != 1:
        return None
    consumer_identity = next(iter(consumer_identities))
    line_start = dependency.line_number or 1
    return {
        "repo": repo_identity_key(consumer_identity),
        "repo_name": consumer_identity.name,
        "repo_identity": consumer_identity.to_json(),
        "path": str(dependency.manifest_path),
        "line_start": line_start,
        "line_end": line_start,
    }


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())
