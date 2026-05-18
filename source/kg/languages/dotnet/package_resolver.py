from __future__ import annotations
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot


DOTNET_PACKAGE_MANIFESTS = ("*.csproj",)
DOTNET_PACKAGE_IGNORED_DIRS = frozenset((*IGNORED_DIRS, "bin", "obj"))
_CACHE_MISS = object()


@dataclass(frozen=True)
class DotnetPackageMetadata:
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None


@dataclass(frozen=True)
class _DotnetProjectMetadata:
    package_name: str
    aliases: frozenset[str]


class DotnetPackageResolver:
    """Resolve C# using namespaces against .NET project metadata."""

    def __init__(self) -> None:
        self._manifest_paths_cache: dict[RepoSnapshot, tuple[Path, ...]] = {}
        self._metadata_cache: dict[RepoSnapshot, DotnetPackageMetadata] = {}

    def manifest_path(self, repo: RepoSnapshot) -> Path | None:
        paths = self.manifest_paths(repo)
        return paths[0] if paths else None

    def manifest_paths(self, repo: RepoSnapshot) -> tuple[Path, ...]:
        cached = self._manifest_paths_cache.get(repo, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        paths = tuple(
            sorted(
                path
                for path in repo.root.rglob("*.csproj")
                if not any(part in DOTNET_PACKAGE_IGNORED_DIRS for part in path.relative_to(repo.root).parts)
            )
        )
        self._manifest_paths_cache[repo] = paths
        return paths

    def package_metadata(self, repo: RepoSnapshot) -> DotnetPackageMetadata:
        cached = self._metadata_cache.get(repo)
        if cached is not None:
            return cached
        manifest_paths = self.manifest_paths(repo)
        if not manifest_paths:
            metadata = DotnetPackageMetadata(repo.name, frozenset((repo.name,)), None)
            self._metadata_cache[repo] = metadata
            return metadata

        aliases = {repo.name}
        primary_package_name: str | None = None
        primary_manifest_path: Path | None = None
        for manifest_path in manifest_paths:
            if not manifest_path.is_file():
                raise ValueError(f"Package manifest path is not a file: {manifest_path}")
            project_metadata = _csproj_metadata(manifest_path)
            aliases.update(project_metadata.aliases)
            if primary_package_name is None:
                primary_package_name = project_metadata.package_name
                primary_manifest_path = manifest_path

        metadata = DotnetPackageMetadata(
            primary_package_name or repo.name,
            frozenset(alias for alias in aliases if alias),
            primary_manifest_path or manifest_paths[0],
        )
        self._metadata_cache[repo] = metadata
        return metadata

    def resolve(self, import_root: str, target_repos: Iterable[RepoSnapshot]) -> str | None:
        normalized_root = _normalize_dotnet_name(import_root)
        if not normalized_root:
            return None
        matches = [
            metadata
            for repo in target_repos
            for metadata in (self.package_metadata(repo),)
            if _matches_dotnet_alias(normalized_root, metadata.aliases)
        ]
        return matches[0].package_name if len(matches) == 1 else None


def _csproj_metadata(path: Path) -> _DotnetProjectMetadata:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ET.ParseError):
        return _DotnetProjectMetadata(path.stem, frozenset((path.stem,)))
    values_by_property: dict[str, set[str]] = {
        "PackageId": set(),
        "AssemblyName": set(),
        "RootNamespace": set(),
        "MSBuildProjectName": set(),
    }
    for node in root.iter():
        property_name = _local_name(node.tag)
        if property_name not in values_by_property:
            continue
        value = _non_empty_string(node.text)
        if value is not None:
            values_by_property[property_name].add(value)
    aliases = {path.stem}
    for values in values_by_property.values():
        aliases.update(values)
    for preferred_name in ("PackageId", "AssemblyName", "RootNamespace", "MSBuildProjectName"):
        values = values_by_property[preferred_name]
        if values:
            return _DotnetProjectMetadata(sorted(values)[0], frozenset(aliases))
    return _DotnetProjectMetadata(path.stem, frozenset(aliases))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _matches_dotnet_alias(normalized_root: str, aliases: Iterable[str]) -> bool:
    for alias in aliases:
        normalized_alias = _normalize_dotnet_name(alias)
        if not normalized_alias:
            continue
        if normalized_root == normalized_alias or normalized_root.startswith(f"{normalized_alias}."):
            return True
    return False


def _normalize_dotnet_name(name: str) -> str:
    normalized = name.strip().lower().replace("-", ".").replace("_", ".")
    while ".." in normalized:
        normalized = normalized.replace("..", ".")
    return normalized.strip(".")


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
