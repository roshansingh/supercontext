from __future__ import annotations

from importlib import import_module
from pathlib import Path

from source.kg.languages.types import LanguageFileMatcher


def discover_language_file_matchers(
    package_root: Path | None = None,
    package_name: str | None = None,
) -> tuple[LanguageFileMatcher, ...]:
    root = package_root or Path(__file__).parent
    base_package = package_name or __package__
    if base_package is None:
        raise ValueError("package_name is required when package context is unavailable")

    matchers: list[LanguageFileMatcher] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith("_") or child.name == "__pycache__":
            continue
        module = import_module(f"{base_package}.{child.name}.files")
        matcher = getattr(module, "LANGUAGE_FILES", None)
        if matcher is None:
            raise ValueError(f"{child.name}.files must export LANGUAGE_FILES")
        _validate_language_file_matcher(matcher)
        matchers.append(matcher)
    _validate_unique_language_names(matchers)
    return tuple(matchers)


def _validate_language_file_matcher(matcher: LanguageFileMatcher) -> None:
    if not matcher.name:
        raise ValueError("Language file matcher must declare a name")
    if not isinstance(matcher.aliases, tuple) or not all(isinstance(alias, str) for alias in matcher.aliases):
        raise ValueError(f"{matcher.name} aliases must be tuple[str, ...]")
    if not isinstance(matcher.file_extensions, frozenset) or not all(
        isinstance(extension, str) for extension in matcher.file_extensions
    ):
        raise ValueError(f"{matcher.name} file_extensions must be frozenset[str]")
    if not isinstance(matcher.manifest_files, frozenset) or not all(
        isinstance(filename, str) for filename in matcher.manifest_files
    ):
        raise ValueError(f"{matcher.name} manifest_files must be frozenset[str]")
    if not callable(getattr(matcher, "matches_file", None)):
        raise ValueError(f"{matcher.name} must implement matches_file(path)")


def _validate_unique_language_names(matchers: list[LanguageFileMatcher]) -> None:
    seen: set[str] = set()
    for matcher in matchers:
        if matcher.name in seen:
            raise ValueError(f"Duplicate language file matcher name: {matcher.name}")
        seen.add(matcher.name)


REGISTERED_LANGUAGE_FILES = discover_language_file_matchers(Path(__file__).parent, __package__)


__all__ = ["REGISTERED_LANGUAGE_FILES", "discover_language_file_matchers"]
