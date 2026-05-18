from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
import json
import re
import subprocess
import tomllib

from source.kg.core.models import Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import read_jsonl
from source.kg.core.tenant import resolve_tenant_id


LINKER_SOURCE_SYSTEM = "package_linker"
LINKER_RULE_VERSION = "package-linker-1"
STALE_SNAPSHOT_OUTPUT_FILES = frozenset(
    ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl", "metrics.jsonl")
)


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


def link_external_packages(inputs: list[LinkerInput] | tuple[LinkerInput, ...]) -> LinkerResult:
    providers = _package_providers(inputs)
    entity_repo_identities: dict[str, set[RepoIdentity]] = {}
    entities: list[Entity] = []
    for input_repo in inputs:
        entities.extend(input_repo.entities)
        for entity in input_repo.entities:
            if entity.kind == "ExternalPackage":
                entity_repo_identities.setdefault(entity.entity_id, set()).add(input_repo.repo_identity)

    link_facts, link_evidence, ambiguous_count = _link_external_packages(entities, providers, entity_repo_identities)
    return LinkerResult(
        facts=tuple(link_facts),
        evidence=tuple(link_evidence),
        providers=tuple(providers),
        ambiguous_package_count=ambiguous_count,
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
    _remove_stale_snapshot_outputs(out)
    _write_jsonl(out / "cross_repo_links.jsonl", (fact.to_record() for fact in result.facts), "fact_id")
    _write_jsonl(
        out / "cross_repo_link_evidence.jsonl",
        (row.to_record() for row in result.evidence),
        "evidence_id",
    )
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
        "counts": {
            "facts": len({fact.fact_id for fact in result.facts}),
            "evidence": len({row.evidence_id for row in result.evidence}),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _remove_stale_snapshot_outputs(out: Path) -> None:
    for filename in STALE_SNAPSHOT_OUTPUT_FILES:
        stale_path = out / filename
        if stale_path.exists():
            if not stale_path.is_file():
                raise ValueError(f"Cannot replace stale snapshot artifact because it is not a file: {stale_path}")
            stale_path.unlink()


def resolve_snapshot_dirs(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    snapshots: list[Path] = []
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
    if manifest.get("build_type") == "fleet_relink":
        return "fleet"
    if _is_repo_snapshot_manifest(manifest):
        return "repo"
    return "invalid"


def _read_manifest_object(path: Path) -> JsonObject:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return manifest


def _is_repo_snapshot_manifest(manifest: JsonObject) -> bool:
    return (
        manifest.get("build_type") != "fleet_relink"
        and isinstance(manifest.get("repo_path"), str)
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
    repo_name = manifest.get("repo_name")
    owner = manifest.get("owner")
    repo = RepoSnapshot(
        repo_root,
        repo_name if isinstance(repo_name, str) and repo_name else repo_root.name,
        owner if isinstance(owner, str) and owner else repo_root.parent.name,
        commit_sha,
        {},
    )
    resolved_tenant = _snapshot_tenant_id(manifest, tenant_id)
    entities = tuple(
        _entity_from_record(row, root / "entities.jsonl")
        for row in _read_entity_rows(root / "entities.jsonl")
    )
    _validate_unique_entity_ids(entities, root / "entities.jsonl")
    return LinkerInput(
        repo=repo,
        repo_identity=repo_identity(repo, resolved_tenant),
        entities=entities,
        validate_package_manifests=True,
        snapshot_dir=root,
    )


def _snapshot_tenant_id(manifest: JsonObject, tenant_id: str | None) -> str:
    manifest_tenant = manifest.get("tenant_id")
    if "tenant_id" in manifest:
        if not isinstance(manifest_tenant, str) or not manifest_tenant.strip():
            raise ValueError("snapshot manifest tenant_id must be a non-empty string when present")
        resolved_manifest_tenant = resolve_tenant_id(manifest_tenant)
    else:
        resolved_manifest_tenant = resolve_tenant_id(None)
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
    rows = read_jsonl(path)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
    return tuple(rows)


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
    if canonical_status not in {"canonical", "candidate", "demoted"}:
        raise ValueError(f"{path}: entity canonical_status is unsupported: {canonical_status}")
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


def _package_providers(inputs: list[LinkerInput] | tuple[LinkerInput, ...]) -> list[PackageProvider]:
    providers: list[PackageProvider] = []
    for input_repo in inputs:
        repo = input_repo.repo
        entities = list(input_repo.entities)
        repo_entity = _select_repo_entity(entities, input_repo.repo_identity)
        if repo_entity is None:
            continue
        service_entities = [entity for entity in entities if entity.kind == "Service"]
        package_name, aliases, manifest_path = _package_metadata(
            repo,
            validate_snapshot_manifest=input_repo.validate_package_manifests,
        )
        service_entity = _select_service_entity(service_entities, aliases)
        providers.append(
            PackageProvider(
                repo=repo,
                repo_identity=input_repo.repo_identity,
                package_name=package_name,
                aliases=tuple(sorted({alias for alias in aliases if alias})),
                manifest_path=manifest_path,
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


def _select_service_entity(services: list[Entity], aliases: set[str]) -> Entity | None:
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
    pyproject = repo.root / "pyproject.toml"
    if pyproject.exists():
        if validate_snapshot_manifest:
            _validate_manifest_file_matches_snapshot(repo, pyproject)
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        package_name = _pyproject_package_name(data) or repo.name
        aliases = {package_name, repo.name}
        aliases.update(_python_package_roots(data, repo))
        return package_name, aliases, pyproject

    package_json = repo.root / "package.json"
    if validate_snapshot_manifest:
        _validate_missing_manifest_file_matches_snapshot(repo, pyproject)
    if package_json.exists():
        if validate_snapshot_manifest:
            _validate_manifest_file_matches_snapshot(repo, package_json)
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        package_name = str(data.get("name") or repo.name)
        aliases = {package_name, repo.name, _unscoped_package_name(package_name)}
        return package_name, aliases, package_json

    if validate_snapshot_manifest:
        _validate_repo_commit_matches_snapshot(repo)
        _validate_missing_manifest_file_matches_snapshot(repo, package_json)
    return repo.name, {repo.name}, None


def _validate_manifest_file_matches_snapshot(repo: RepoSnapshot, manifest_path: Path) -> None:
    _validate_repo_commit_matches_snapshot(repo)
    if repo.commit_sha == "working-tree":
        return
    status = _git_status_porcelain(repo.root, manifest_path)
    if status:
        relative = manifest_path.relative_to(repo.root)
        raise ValueError(f"Package manifest has uncommitted changes relative to snapshot commit: {relative}")


def _validate_missing_manifest_file_matches_snapshot(repo: RepoSnapshot, manifest_path: Path) -> None:
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


def _python_package_roots(data: JsonObject, repo: RepoSnapshot) -> set[str]:
    roots = {repo.name}
    tool = data.get("tool") if isinstance(data, dict) else None
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    packages = poetry.get("packages", []) if isinstance(poetry, dict) else []
    if not isinstance(packages, list):
        return roots
    for package in packages:
        include = package.get("include") if isinstance(package, dict) else None
        if include:
            roots.add(str(include).split(".", 1)[0])
    return roots


def _pyproject_package_name(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    poetry_name = poetry.get("name") if isinstance(poetry, dict) else None
    if isinstance(poetry_name, str) and poetry_name:
        return poetry_name
    project = data.get("project")
    project_name = project.get("name") if isinstance(project, dict) else None
    if isinstance(project_name, str) and project_name:
        return project_name
    return None


def _link_external_packages(
    entities: list[Entity],
    providers: list[PackageProvider],
    entity_repo_identities: dict[str, set[RepoIdentity]],
) -> tuple[list[Fact], list[Evidence], int]:
    provider_index: dict[str, list[PackageProvider]] = {}
    for provider in providers:
        for alias in provider.aliases:
            provider_index.setdefault(_normalize_package_name(alias), []).append(provider)

    facts: list[Fact] = []
    evidence: list[Evidence] = []
    ambiguous_count = 0
    packages_by_id: dict[str, list[Entity]] = {}
    for entity in entities:
        if entity.kind == "ExternalPackage":
            packages_by_id.setdefault(entity.entity_id, []).append(entity)
    for package_group in packages_by_id.values():
        if any(_is_builtin_package(package) for package in package_group):
            continue
        package = package_group[0]
        consumer_identities = entity_repo_identities.get(package.entity_id, set())
        candidate_names = _external_package_candidate_names(package)
        matches = {
            provider
            for name in candidate_names
            for provider in provider_index.get(_normalize_package_name(name), [])
            if not _is_self_link(provider, package, consumer_identities)
        }
        if not matches:
            continue
        if len(matches) > 1:
            ambiguous_count += 1
            continue
        provider = next(iter(matches))
        matched_name = _matched_name(candidate_names, provider)
        package_facts = [
            Fact(
                predicate="RESOLVES_TO_REPO",
                subject_id=package.entity_id,
                object_id=provider.repo_entity_id,
                qualifier=_link_qualifier(package, provider, matched_name, consumer_identities),
            )
        ]
        if provider.service_entity_id is not None:
            package_facts.append(
                Fact(
                    predicate="RESOLVES_TO_SERVICE",
                    subject_id=package.entity_id,
                    object_id=provider.service_entity_id,
                    qualifier=_link_qualifier(package, provider, matched_name, consumer_identities),
                )
            )
        facts.extend(package_facts)
        evidence.extend(_link_evidence(package, provider, package_facts, consumer_identities))
    return facts, evidence, ambiguous_count


def _is_self_link(provider: PackageProvider, package: Entity, consumer_identities: set[RepoIdentity]) -> bool:
    if not consumer_identities:
        raise ValueError(
            "ExternalPackage entity missing repo identity tracking: "
            f"entity_id={package.entity_id}, identity={package.identity}"
        )
    return provider.repo_identity in consumer_identities


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
    return package.properties.get("category") in {"stdlib", "node_builtin"}


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
) -> JsonObject:
    qualifier: JsonObject = {
        "rule": "unique_normalized_package_name_match",
        "rule_version": LINKER_RULE_VERSION,
        "consumer_repo": package.identity.get("repo"),
        "package_name": package.identity.get("name"),
        "matched_name": matched_name,
        "provider_repo": provider.repo.name,
        "provider_repo_identity": provider.repo_identity.to_json(),
        "provider_package_name": provider.package_name,
    }
    qualifier.update(_consumer_identity_ref(consumer_identities))
    return qualifier


def _link_evidence(
    package: Entity,
    provider: PackageProvider,
    facts: list[Fact],
    consumer_identities: set[RepoIdentity],
) -> list[Evidence]:
    return [
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
            source_system=LINKER_SOURCE_SYSTEM,
            source_ref={
                "rule": "unique_normalized_package_name_match",
                "rule_version": LINKER_RULE_VERSION,
                "consumer_repo": package.identity.get("repo"),
                **_consumer_identity_ref(consumer_identities),
                "provider_repo": provider.repo.name,
                "provider_repo_identity": provider.repo_identity.to_json(),
                "provider_package_name": provider.package_name,
            },
            bytes_ref=_manifest_bytes_ref(provider),
            confidence=1.0,
        )
        for fact in facts
    ]


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


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _unscoped_package_name(name: str) -> str:
    return name.rsplit("/", 1)[-1] if name.startswith("@") else name
