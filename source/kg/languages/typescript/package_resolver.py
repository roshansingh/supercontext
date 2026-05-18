from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot


TYPESCRIPT_PACKAGE_MANIFESTS = ("package.json",)
_CACHE_MISS = object()


@dataclass(frozen=True)
class TypeScriptPackageMetadata:
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None


class TypeScriptPackageResolver:
    """Resolve JS/TS import roots against npm package metadata."""

    def __init__(self) -> None:
        self._manifest_paths_cache: dict[RepoSnapshot, tuple[Path, ...]] = {}
        self._metadata_cache: dict[RepoSnapshot, TypeScriptPackageMetadata] = {}

    def manifest_path(self, repo: RepoSnapshot) -> Path | None:
        paths = self.manifest_paths(repo)
        return paths[0] if paths else None

    def manifest_paths(self, repo: RepoSnapshot) -> tuple[Path, ...]:
        cached = self._manifest_paths_cache.get(repo, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        paths = tuple(
            repo.root / filename
            for filename in TYPESCRIPT_PACKAGE_MANIFESTS
            if (repo.root / filename).exists()
        )
        self._manifest_paths_cache[repo] = paths
        return paths

    def package_metadata(self, repo: RepoSnapshot) -> TypeScriptPackageMetadata:
        cached = self._metadata_cache.get(repo)
        if cached is not None:
            return cached
        manifest_path = self.manifest_path(repo)
        if manifest_path is None:
            metadata = TypeScriptPackageMetadata(repo.name, frozenset((repo.name,)), None)
            self._metadata_cache[repo] = metadata
            return metadata
        if not manifest_path.is_file():
            raise ValueError(f"Package manifest path is not a file: {manifest_path}")

        package_name = _package_json_name(manifest_path) or repo.name
        aliases = frozenset(alias for alias in (repo.name, package_name) if alias)
        metadata = TypeScriptPackageMetadata(package_name, aliases, manifest_path)
        self._metadata_cache[repo] = metadata
        return metadata

    def resolve(self, import_root: str, target_repos: Iterable[RepoSnapshot]) -> str | None:
        normalized_root = _normalize_package_name(import_root)
        matches = [
            metadata
            for repo in target_repos
            for metadata in (self.package_metadata(repo),)
            if normalized_root in {_normalize_package_name(alias) for alias in metadata.aliases}
        ]
        return matches[0].package_name if len(matches) == 1 else None


def _package_json_name(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_name = data.get("name")
    return raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())
