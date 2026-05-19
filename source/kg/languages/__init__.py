from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from source.kg.languages.types import LanguageSupport

if TYPE_CHECKING:
    from source.kg.extraction.framework.adapter import Adapter

_REGISTERED_LANGUAGES: tuple[LanguageSupport, ...] | None = None


def discover_languages(
    package_root: Path | None = None,
    package_name: str | None = None,
) -> tuple[LanguageSupport, ...]:
    root = package_root or Path(__file__).parent
    base_package = package_name or __package__
    if base_package is None:
        raise ValueError("package_name is required when package context is unavailable")

    languages: list[LanguageSupport] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith("_") or child.name == "__pycache__":
            continue
        module = import_module(f"{base_package}.{child.name}.language")
        language = getattr(module, "LANGUAGE_SUPPORT", None)
        if language is None:
            raise ValueError(f"{child.name}.language must export LANGUAGE_SUPPORT")
        _validate_language(language)
        languages.append(language)
    _validate_unique_language_names(languages)
    return tuple(languages)


def language_adapters(languages: tuple[LanguageSupport, ...] | None = None) -> tuple[Adapter, ...]:
    adapters: list[Adapter] = []
    for language in _registered_languages() if languages is None else languages:
        adapters.extend(language.adapters())
    return tuple(adapters)


def _registered_languages() -> tuple[LanguageSupport, ...]:
    global _REGISTERED_LANGUAGES
    if _REGISTERED_LANGUAGES is None:
        _REGISTERED_LANGUAGES = discover_languages(Path(__file__).parent, __package__)
    return _REGISTERED_LANGUAGES


def _validate_language(language: LanguageSupport) -> None:
    if not language.name:
        raise ValueError("Language support must declare a name")
    if not isinstance(language.aliases, tuple) or not all(isinstance(alias, str) for alias in language.aliases):
        raise ValueError(f"{language.name} aliases must be tuple[str, ...]")
    if not isinstance(language.file_extensions, frozenset) or not all(
        isinstance(extension, str) for extension in language.file_extensions
    ):
        raise ValueError(f"{language.name} file_extensions must be frozenset[str]")
    if not isinstance(language.manifest_files, frozenset) or not all(
        isinstance(filename, str) for filename in language.manifest_files
    ):
        raise ValueError(f"{language.name} manifest_files must be frozenset[str]")
    for method_name in (
        "matches_file",
        "source_roots",
        "parse_repo",
        "opportunity_detectors",
        "package_resolver",
        "consumer_manifest_extractor",
        "dimension_rules",
        "useful_edges",
        "adapters",
        "known_stacks",
    ):
        if not callable(getattr(language, method_name, None)):
            raise ValueError(f"{language.name} must implement {method_name}()")


def _validate_unique_language_names(languages: list[LanguageSupport]) -> None:
    seen: set[str] = set()
    for language in languages:
        if language.name in seen:
            raise ValueError(f"Duplicate language support name: {language.name}")
        seen.add(language.name)


def __getattr__(name: str):
    if name == "REGISTERED_LANGUAGES":
        return _registered_languages()
    raise AttributeError(name)


__all__ = ["REGISTERED_LANGUAGES", "discover_languages", "language_adapters"]
