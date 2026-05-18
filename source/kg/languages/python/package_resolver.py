from __future__ import annotations

import ast
import configparser
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.python.normalization.imports import KNOWN_IMPORT_ROOT_DISTRIBUTIONS


PYTHON_PACKAGE_MANIFESTS = ("pyproject.toml", "setup.cfg", "setup.py")
_CACHE_MISS = object()


@dataclass(frozen=True)
class PythonPackageMetadata:
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None


class PythonPackageResolver:
    """Resolve Python import roots against repo package metadata."""

    def __init__(self) -> None:
        self._manifest_path_cache: dict[RepoSnapshot, Path | None] = {}
        self._metadata_cache: dict[RepoSnapshot, PythonPackageMetadata] = {}

    def manifest_path(self, repo: RepoSnapshot) -> Path | None:
        cached = self._manifest_path_cache.get(repo, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        for filename in PYTHON_PACKAGE_MANIFESTS:
            path = repo.root / filename
            if path.exists():
                self._manifest_path_cache[repo] = path
                return path
        self._manifest_path_cache[repo] = None
        return None

    def package_metadata(self, repo: RepoSnapshot) -> PythonPackageMetadata:
        cached = self._metadata_cache.get(repo)
        if cached is not None:
            return cached
        manifest_path = self.manifest_path(repo)
        if manifest_path is None:
            metadata = PythonPackageMetadata(repo.name, frozenset((repo.name,)), None)
            self._metadata_cache[repo] = metadata
            return metadata
        if not manifest_path.is_file():
            raise ValueError(f"Package manifest path is not a file: {manifest_path}")

        package_name = repo.name
        aliases = {repo.name}
        if manifest_path.name == "pyproject.toml":
            data = _read_pyproject(manifest_path)
            package_name = _pyproject_package_name(data) or repo.name
            aliases.update(_pyproject_package_roots(data, repo))
        elif manifest_path.name == "setup.cfg":
            package_name = _setup_cfg_package_name(manifest_path) or repo.name
        elif manifest_path.name == "setup.py":
            package_name = _setup_py_package_name(manifest_path) or repo.name

        aliases.add(package_name)
        metadata = PythonPackageMetadata(package_name, frozenset(alias for alias in aliases if alias), manifest_path)
        self._metadata_cache[repo] = metadata
        return metadata

    def resolve(self, import_root: str, target_repos: Iterable[RepoSnapshot]) -> str | None:
        candidates = {_normalize_package_name(name) for name in _import_root_candidates(import_root)}
        matches = [
            metadata
            for repo in target_repos
            for metadata in (self.package_metadata(repo),)
            if candidates.intersection(_normalize_package_name(alias) for alias in metadata.aliases)
        ]
        return matches[0].package_name if len(matches) == 1 else None


def _read_pyproject(path: Path) -> object:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


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


def _pyproject_package_roots(data: object, repo: RepoSnapshot) -> set[str]:
    roots = {repo.name}
    if not isinstance(data, dict):
        return roots
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    packages = poetry.get("packages", []) if isinstance(poetry, dict) else []
    if not isinstance(packages, list):
        return roots
    for package in packages:
        include = package.get("include") if isinstance(package, dict) else None
        if isinstance(include, str) and include:
            roots.add(include.split(".", 1)[0])
    return roots


def _setup_cfg_package_name(path: Path) -> str | None:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
        value = parser.get("metadata", "name", fallback=None)
    except configparser.Error:
        return None
    if not parser.has_section("metadata"):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _setup_py_package_name(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_setup_call(node.func):
            continue
        for keyword in node.keywords:
            # setup.py execution is intentionally unsupported; v1 accepts only static literal names.
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                value = keyword.value.value
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _is_setup_call(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "setup"
    return isinstance(node, ast.Attribute) and node.attr == "setup"


def _import_root_candidates(import_root: str) -> set[str]:
    stripped = import_root.strip()
    if not stripped:
        return set()
    candidates = {stripped, stripped.replace("_", "-")}
    candidates.update(KNOWN_IMPORT_ROOT_DISTRIBUTIONS.get(stripped.lower(), ()))
    return candidates


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())
