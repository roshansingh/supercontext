from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable, Protocol

from source.kg.build.multi_repo import build_multi_kg
from source.kg.core.models import JsonObject, utc_now_iso


CONFIG_FILENAME = "config.json"
STATE_FILENAME = "state.json"
DEFAULT_HOME_ROOT = Path.home() / ".supercontext" / "orgs"


@dataclass(frozen=True)
class DiscoveredRepo:
    name: str
    full_name: str
    clone_url: str
    default_branch: str = "main"
    archived: bool = False


@dataclass(frozen=True)
class OrgConfig:
    provider: str
    org: str
    home: Path
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    clone_protocol: str = "https"

    @property
    def repos_dir(self) -> Path:
        return self.home / "repos"

    @property
    def snapshot_dir(self) -> Path:
        return self.home / "kg"


@dataclass(frozen=True)
class LocalRepoState:
    name: str
    full_name: str
    clone_url: str
    default_branch: str
    local_path: Path
    commit_sha: str
    synced_at: str


@dataclass(frozen=True)
class OrgState:
    repos: tuple[LocalRepoState, ...] = ()
    last_synced_at: str | None = None
    last_built_at: str | None = None
    last_build_fingerprint: str | None = None
    last_sync_errors: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class SyncResult:
    repo_count: int
    changed_count: int
    unchanged_count: int
    failed_count: int
    errors: tuple[JsonObject, ...]
    state_path: Path


@dataclass(frozen=True)
class BuildResult:
    skipped: bool
    repo_count: int
    snapshot_dir: Path
    fingerprint: str
    manifest: JsonObject | None = None


class RepoProvider(Protocol):
    def list_repos(self) -> list[DiscoveredRepo]:
        raise NotImplementedError


class RepoSyncClient(Protocol):
    def sync_repo(self, repo: DiscoveredRepo, destination: Path) -> str:
        raise NotImplementedError


BuildMultiKgFunc = Callable[..., JsonObject]
SyncProgress = Callable[[int, int, DiscoveredRepo], None]
BuildProgress = Callable[[int, int, Path], None]


def default_org_home(provider: str, org: str) -> Path:
    return DEFAULT_HOME_ROOT / _safe_path_part(provider) / _safe_path_part(org)


def init_org(
    provider: str,
    org: str,
    home: str | Path | None = None,
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    clone_protocol: str = "https",
) -> OrgConfig:
    config = OrgConfig(
        provider=provider,
        org=org,
        home=Path(home).expanduser().resolve() if home else default_org_home(provider, org),
        include=tuple(include),
        exclude=tuple(exclude),
        clone_protocol=clone_protocol,
    )
    _validate_config(config)
    config.home.mkdir(parents=True, exist_ok=True)
    _write_json(config.home / CONFIG_FILENAME, _config_to_json(config))
    if not (config.home / STATE_FILENAME).exists():
        save_org_state(config.home, OrgState())
    return config


def load_org_config(home: str | Path) -> OrgConfig:
    home_path = Path(home).expanduser().resolve()
    data = _read_json_object(home_path / CONFIG_FILENAME)
    provider = _required_str(data, "provider", CONFIG_FILENAME)
    org = _required_str(data, "org", CONFIG_FILENAME)
    include = tuple(_string_list(data, "include", CONFIG_FILENAME))
    exclude = tuple(_string_list(data, "exclude", CONFIG_FILENAME))
    clone_protocol = data.get("clone_protocol", "https")
    if not isinstance(clone_protocol, str):
        raise ValueError("config.json field clone_protocol must be a string")
    config = OrgConfig(
        provider=provider,
        org=org,
        home=home_path,
        include=include,
        exclude=exclude,
        clone_protocol=clone_protocol,
    )
    _validate_config(config)
    return config


def load_org_state(home: str | Path) -> OrgState:
    home_path = Path(home).expanduser().resolve()
    path = home_path / STATE_FILENAME
    if not path.exists():
        return OrgState()
    data = _read_json_object(path)
    repos_value = data.get("repos", [])
    if not isinstance(repos_value, list):
        raise ValueError("state.json field repos must be a list")
    repos: list[LocalRepoState] = []
    for index, row in enumerate(repos_value):
        if not isinstance(row, dict):
            raise ValueError(f"state.json repos[{index}] must be an object")
        repos.append(_repo_state_from_json(row, home_path, index))
    return OrgState(
        repos=tuple(repos),
        last_synced_at=_optional_str(data, "last_synced_at", STATE_FILENAME),
        last_built_at=_optional_str(data, "last_built_at", STATE_FILENAME),
        last_build_fingerprint=_optional_str(data, "last_build_fingerprint", STATE_FILENAME),
        last_sync_errors=tuple(_json_object_list(data, "last_sync_errors", STATE_FILENAME)),
    )


def save_org_state(home: str | Path, state: OrgState) -> None:
    home_path = Path(home).expanduser().resolve()
    _write_json(home_path / STATE_FILENAME, _state_to_json(state, home_path))


def sync_org(
    home: str | Path,
    provider: RepoProvider | None = None,
    git_client: RepoSyncClient | None = None,
    progress: SyncProgress | None = None,
    continue_on_error: bool = True,
) -> SyncResult:
    from source.kg.org.git import GitClient
    from source.kg.org.github import GitHubCliRepoProvider

    config = load_org_config(home)
    provider = provider or GitHubCliRepoProvider(
        org=config.org,
        clone_protocol=config.clone_protocol,
    )
    git_client = git_client or GitClient()
    previous_state = load_org_state(config.home)
    previous_by_full_name = {repo.full_name: repo for repo in previous_state.repos}
    now = utc_now_iso()
    repos: list[LocalRepoState] = []
    errors: list[JsonObject] = []
    changed_count = 0
    succeeded_count = 0
    discovered_repos = _filter_repos(provider.list_repos(), config)
    total = len(discovered_repos)
    for index, discovered in enumerate(discovered_repos, start=1):
        if progress is not None:
            progress(index, total, discovered)
        destination = config.repos_dir / _safe_path_part(discovered.name)
        try:
            commit_sha = git_client.sync_repo(discovered, destination)
        except Exception as exc:
            if not continue_on_error:
                raise
            errors.append(
                {
                    "repo": discovered.full_name,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
            previous = previous_by_full_name.get(discovered.full_name)
            if previous is not None:
                repos.append(previous)
            continue
        previous = previous_by_full_name.get(discovered.full_name)
        if previous is None or previous.commit_sha != commit_sha:
            changed_count += 1
        succeeded_count += 1
        repos.append(
            LocalRepoState(
                name=discovered.name,
                full_name=discovered.full_name,
                clone_url=discovered.clone_url,
                default_branch=discovered.default_branch,
                local_path=destination,
                commit_sha=commit_sha,
                synced_at=now,
            )
        )
    state = OrgState(
        repos=tuple(sorted(repos, key=lambda repo: repo.full_name)),
        last_synced_at=now,
        last_built_at=previous_state.last_built_at,
        last_build_fingerprint=previous_state.last_build_fingerprint,
        last_sync_errors=tuple(errors),
    )
    save_org_state(config.home, state)
    return SyncResult(
        repo_count=total,
        changed_count=changed_count,
        unchanged_count=succeeded_count - changed_count,
        failed_count=len(errors),
        errors=tuple(errors),
        state_path=config.home / STATE_FILENAME,
    )


def build_org(
    home: str | Path,
    force: bool = False,
    strict_extractors: bool = False,
    tenant_id: str | None = None,
    build_multi_kg_func: BuildMultiKgFunc = build_multi_kg,
    progress: BuildProgress | None = None,
) -> BuildResult:
    config = load_org_config(home)
    state = load_org_state(config.home)
    if not state.repos:
        raise ValueError("No synced repositories found. Run 'supercontext org sync' first.")
    fingerprint = _build_fingerprint(state)
    if not force and state.last_build_fingerprint == fingerprint and (config.snapshot_dir / "manifest.json").exists():
        return BuildResult(
            skipped=True,
            repo_count=len(state.repos),
            snapshot_dir=config.snapshot_dir,
            fingerprint=fingerprint,
        )
    repo_paths = [repo.local_path for repo in state.repos]
    manifest = build_multi_kg_func(
        repo_paths,
        config.snapshot_dir,
        strict_extractors=strict_extractors,
        tenant_id=tenant_id or config.org,
        progress=progress,
        repo_owner=config.org,
    )
    save_org_state(
        config.home,
        OrgState(
            repos=state.repos,
            last_synced_at=state.last_synced_at,
            last_built_at=utc_now_iso(),
            last_build_fingerprint=fingerprint,
            last_sync_errors=state.last_sync_errors,
        ),
    )
    return BuildResult(
        skipped=False,
        repo_count=len(state.repos),
        snapshot_dir=config.snapshot_dir,
        fingerprint=fingerprint,
        manifest=manifest,
    )


def _filter_repos(repos: list[DiscoveredRepo], config: OrgConfig) -> list[DiscoveredRepo]:
    selected: list[DiscoveredRepo] = []
    for repo in repos:
        if config.include and not any(_repo_matches(repo, pattern) for pattern in config.include):
            continue
        if config.exclude and any(_repo_matches(repo, pattern) for pattern in config.exclude):
            continue
        selected.append(repo)
    return selected


def _repo_matches(repo: DiscoveredRepo, pattern: str) -> bool:
    return fnmatch(repo.full_name, pattern) or fnmatch(repo.name, pattern)


def _build_fingerprint(state: OrgState) -> str:
    payload = [
        {
            "full_name": repo.full_name,
            "commit_sha": repo.commit_sha,
        }
        for repo in sorted(state.repos, key=lambda item: item.full_name)
    ]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _config_to_json(config: OrgConfig) -> JsonObject:
    return {
        "provider": config.provider,
        "org": config.org,
        "include": list(config.include),
        "exclude": list(config.exclude),
        "clone_protocol": config.clone_protocol,
    }


def _state_to_json(state: OrgState, home: Path) -> JsonObject:
    return {
        "last_synced_at": state.last_synced_at,
        "last_built_at": state.last_built_at,
        "last_build_fingerprint": state.last_build_fingerprint,
        "last_sync_errors": list(state.last_sync_errors),
        "repos": [
            {
                "name": repo.name,
                "full_name": repo.full_name,
                "clone_url": repo.clone_url,
                "default_branch": repo.default_branch,
                "local_path": _relative_to_home(repo.local_path, home),
                "commit_sha": repo.commit_sha,
                "synced_at": repo.synced_at,
            }
            for repo in state.repos
        ],
    }


def _repo_state_from_json(row: dict[str, object], home: Path, index: int) -> LocalRepoState:
    local_path = _required_str(row, "local_path", f"state.json repos[{index}]")
    path = Path(local_path)
    if not path.is_absolute():
        path = home / path
    return LocalRepoState(
        name=_required_str(row, "name", f"state.json repos[{index}]"),
        full_name=_required_str(row, "full_name", f"state.json repos[{index}]"),
        clone_url=_required_str(row, "clone_url", f"state.json repos[{index}]"),
        default_branch=_required_str(row, "default_branch", f"state.json repos[{index}]"),
        local_path=path.resolve(),
        commit_sha=_required_str(row, "commit_sha", f"state.json repos[{index}]"),
        synced_at=_required_str(row, "synced_at", f"state.json repos[{index}]"),
    )


def _relative_to_home(path: Path, home: Path) -> str:
    try:
        return path.resolve().relative_to(home.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _safe_path_part(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("Path component must be non-empty and not '.' or '..'")
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Unsafe path component: {value!r}")
    return safe


def _validate_config(config: OrgConfig) -> None:
    _safe_path_part(config.provider)
    _safe_path_part(config.org)
    if config.provider != "github":
        raise ValueError("Only provider='github' is supported in this release")
    if config.clone_protocol not in {"ssh", "https"}:
        raise ValueError("clone_protocol must be 'ssh' or 'https'")
    for field, patterns in (("include", config.include), ("exclude", config.exclude)):
        for index, pattern in enumerate(patterns):
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(f"{field}[{index}] must be a non-empty string")


def _read_json_object(path: Path) -> JsonObject:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"SuperContext org workspace is not initialized: {path.parent}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def _write_json(path: Path, data: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _required_str(row: dict[str, object], field: str, source: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} field {field} must be a non-empty string")
    return value


def _optional_str(row: dict[str, object], field: str, source: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} field {field} must be null or a non-empty string")
    return value


def _string_list(row: dict[str, object], field: str, source: str) -> list[str]:
    value = row.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"{source} field {field} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{source} field {field}[{index}] must be a non-empty string")
        result.append(item)
    return result


def _json_object_list(row: dict[str, object], field: str, source: str) -> list[JsonObject]:
    value = row.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"{source} field {field} must be a list")
    result: list[JsonObject] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{source} field {field}[{index}] must be an object")
        result.append(item)
    return result
