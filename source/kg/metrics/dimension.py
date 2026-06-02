from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot
from source.kg.languages._shared.dimension_rules_loader import SUPPORTED_DIMENSIONS


@dataclass(frozen=True)
class DimensionAssignment:
    dimension: str
    path_prefix: str
    files: tuple[str, ...]
    rule_id: str
    rule_version: str


@dataclass(frozen=True)
class _RepoFeatures:
    files_by_language: dict[str, set[str]]
    imports_by_language: dict[str, set[str]]
    packages_by_language: dict[str, set[str]]
    manifest_names: set[str]
    file_extensions: set[str]


def classify_repo(repo: RepoSnapshot, registered_languages: Iterable[Any] | None = None) -> tuple[DimensionAssignment, ...]:
    languages = tuple(registered_languages) if registered_languages is not None else _registered_languages()
    features = _collect_features(repo, languages)
    files_by_dimension: dict[str, set[str]] = {}
    rule_ids_by_dimension: dict[str, list[str]] = {}
    versions_by_dimension: dict[str, str] = {}

    for language in languages:
        rules_doc = language.dimension_rules()
        rules = rules_doc.get("rules", []) if isinstance(rules_doc, Mapping) else []
        version = str(rules_doc.get("version", "1")) if isinstance(rules_doc, Mapping) else "1"
        language_names = {language.name, *getattr(language, "aliases", ())}
        language_files: set[str] = set()
        for language_name in language_names:
            language_files.update(features.files_by_language.get(language_name, set()))
        if not language_files:
            continue

        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            dimension = str(rule.get("dimension", ""))
            if dimension not in SUPPORTED_DIMENSIONS:
                continue
            if not _rule_matches(rule, language_names, features):
                continue
            files_by_dimension.setdefault(dimension, set()).update(language_files)
            rule_ids_by_dimension.setdefault(dimension, []).append(str(rule.get("id", "unknown-rule")))
            versions_by_dimension.setdefault(dimension, version)

    terraform_files = sorted(path for path in _all_source_paths(repo) if path.endswith(".tf"))
    if terraform_files:
        files_by_dimension.setdefault("iac", set()).update(terraform_files)
        rule_ids_by_dimension.setdefault("iac", []).append("terraform-files")
        versions_by_dimension.setdefault("iac", "1")

    return tuple(
        DimensionAssignment(
            dimension=dimension,
            path_prefix=_common_path_prefix(files),
            files=tuple(sorted(files)),
            rule_id="+".join(sorted(rule_ids_by_dimension.get(dimension, ["unknown-rule"]))),
            rule_version=versions_by_dimension.get(dimension, "1"),
        )
        for dimension, files in sorted(files_by_dimension.items())
    )


def _collect_features(repo: RepoSnapshot, languages: tuple[Any, ...]) -> _RepoFeatures:
    files_by_language: dict[str, set[str]] = {
        language: {str(path.relative_to(repo.root)) for path in paths}
        for language, paths in repo.files_by_language.items()
    }
    imports_by_language = {
        "python": _python_import_roots(repo.files_by_language.get("python", ())),
    }
    source_paths = _all_source_paths(repo)
    return _RepoFeatures(
        files_by_language=files_by_language,
        imports_by_language=imports_by_language,
        packages_by_language=_packages_by_language(repo, languages),
        manifest_names={path.name for path in _iter_repo_files(repo.root)},
        file_extensions={Path(path).suffix for path in source_paths},
    )


def _rule_matches(rule: Mapping[str, Any], language_names: set[str], features: _RepoFeatures) -> bool:
    imports = _normalized_set(rule.get("imports", ()))
    packages = _normalized_set(rule.get("packages", ()))
    manifest_files = set(str(item) for item in rule.get("manifest_files", ()) if isinstance(item, str))
    file_extensions = set(str(item) for item in rule.get("file_extensions", ()) if isinstance(item, str))

    if imports:
        available_imports: set[str] = set()
        for language_name in language_names:
            available_imports.update(features.imports_by_language.get(language_name, set()))
        if imports.intersection(available_imports):
            return True
    if packages:
        available_packages: set[str] = set()
        for language_name in language_names:
            available_packages.update(features.packages_by_language.get(language_name, set()))
        if packages.intersection(available_packages):
            return True
    if manifest_files and manifest_files.intersection(features.manifest_names):
        return True
    if file_extensions and file_extensions.intersection(features.file_extensions):
        return True
    return False


def _python_import_roots(paths: Iterable[Path]) -> set[str]:
    roots: set[str] = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".", 1)[0].lower())
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0].lower())
    return roots


def _packages_by_language(repo: RepoSnapshot, languages: tuple[Any, ...]) -> dict[str, set[str]]:
    packages_by_language: dict[str, set[str]] = {}
    for language in languages:
        language_names = (language.name, *getattr(language, "aliases", ()))
        if not any(repo.files_by_language.get(language_name) for language_name in language_names):
            continue
        package_names = _language_manifest_packages(repo, language)
        if not package_names:
            continue
        for language_name in language_names:
            packages_by_language.setdefault(language_name, set()).update(package_names)
    return packages_by_language


def _language_manifest_packages(repo: RepoSnapshot, language: Any) -> set[str]:
    extractor_factory = getattr(language, "consumer_manifest_extractor", None)
    if not callable(extractor_factory):
        return set()
    extractor = extractor_factory()
    if extractor is None:
        return set()
    result = extractor.extract(repo)
    packages = {
        _normalize_package(dependency.declared_name)
        for dependency in result.dependencies
        if isinstance(dependency.declared_name, str) and dependency.declared_name.strip()
    }
    return packages - {""}


def normalize_package_name(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _normalize_package(value: str) -> str:
    return normalize_package_name(value)


def _normalized_set(values: Any) -> set[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        return set()
    return {_normalize_package(str(value)) for value in values if isinstance(value, str)}


def _all_source_paths(repo: RepoSnapshot) -> tuple[str, ...]:
    paths = {str(path.relative_to(repo.root)) for paths in repo.files_by_language.values() for path in paths}
    paths.update(str(path.relative_to(repo.root)) for path in _iter_repo_files(repo.root, "*.tf"))
    return tuple(sorted(paths))


def _iter_repo_files(root: Path, pattern: str = "*") -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return tuple(sorted(files))


def _common_path_prefix(files: set[str]) -> str:
    if not files:
        return "."
    parents = {str(Path(path).parent) for path in files}
    if parents == {"."}:
        return "."
    try:
        import os

        prefix = os.path.commonpath(sorted(parents))
    except ValueError:
        return "."
    return prefix or "."


def _registered_languages() -> tuple[Any, ...]:
    from source.kg.languages import REGISTERED_LANGUAGES

    return REGISTERED_LANGUAGES
