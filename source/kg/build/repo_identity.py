from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from source.kg.build.relink import RepoIdentity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import DEFAULT_TENANT_ID


_SCP_LIKE_GIT_URL = re.compile(r"^(?:(?P<user>[^@/:]+)@)?(?P<host>[^/:]+):(?P<path>.+)$")


def normalize_git_url(url: str) -> RepoIdentity | None:
    stripped = url.strip()
    if not stripped:
        return None
    if stripped.startswith("git+"):
        stripped = stripped[4:]
    if stripped.startswith("github:"):
        stripped = "https://github.com/" + stripped.split(":", 1)[1]

    parsed = urlparse(stripped)
    if parsed.scheme and parsed.netloc:
        host = _normalize_host(parsed.hostname or parsed.netloc)
        parts = _repo_path_parts(parsed.path)
    else:
        scp_like = _SCP_LIKE_GIT_URL.match(stripped)
        if scp_like is None:
            return None
        host = _normalize_host(scp_like.group("host"))
        parts = _repo_path_parts(scp_like.group("path"))
    if host is None or len(parts) < 2:
        return None
    owner = "/".join(parts[:-1])
    name = _strip_repo_suffix(parts[-1])
    if not owner or not name:
        return None
    return RepoIdentity(DEFAULT_TENANT_ID, host, owner, name)


def resolve_file_path(
    spec: str,
    manifest_path: Path,
    fleet_snapshots: tuple[RepoSnapshot, ...],
) -> RepoSnapshot | None:
    target = _normalize_dependency_path(spec)
    if target is None:
        return None
    base = manifest_path.parent
    candidate = (Path(target) if Path(target).is_absolute() else base / target).resolve(strict=False)

    exact_matches = [repo for repo in fleet_snapshots if repo.root.resolve(strict=False) == candidate]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    containing_matches = [
        repo
        for repo in fleet_snapshots
        if _is_relative_to(candidate, repo.root.resolve(strict=False))
    ]
    return containing_matches[0] if len(containing_matches) == 1 else None


def _normalize_host(host: str) -> str | None:
    normalized = host.strip().lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return normalized or None


def _repo_path_parts(path: str) -> tuple[str, ...]:
    clean = unquote(path).split("?", 1)[0].split("#", 1)[0].strip("/")
    if not clean:
        return ()
    parts = tuple(part for part in clean.split("/") if part)
    if not parts:
        return ()
    return (*parts[:-1], _strip_repo_suffix(parts[-1]))


def _strip_repo_suffix(name: str) -> str:
    return name[:-4] if name.endswith(".git") else name


def _normalize_dependency_path(spec: str) -> str | None:
    stripped = spec.strip()
    if not stripped:
        return None
    for prefix in ("file:", "link:", "portal:"):
        if stripped.startswith(prefix):
            stripped = stripped.split(":", 1)[1]
            break
    stripped = stripped.replace("\\", "/")
    return stripped or None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
