from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from source.kg.languages.types import LanguageFileMatcher


# V1 inventory targets common production source languages. Registered language
# matchers still win first, so supported languages are not reported here.
UNSUPPORTED_SOURCE_EXTENSIONS: Mapping[str, str] = {
    ".bash": "shell",
    ".c": "c-cpp",
    ".cc": "c-cpp",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cpp": "c-cpp",
    ".cs": "dotnet",
    ".cxx": "c-cpp",
    ".dart": "dart",
    ".erl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
    ".h": "c-cpp",
    ".hpp": "c-cpp",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".lua": "lua",
    ".m": "objective-c",
    ".mm": "objective-c",
    ".php": "php",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "shell",
    ".swift": "swift",
    ".zsh": "shell",
}
UNSUPPORTED_LANGUAGE_IGNORED_DIRS = frozenset({"bin", "obj", "out", "target"})


def unsupported_files_by_language(
    root: Path,
    *,
    source_files: tuple[Path, ...],
    language_files: tuple[LanguageFileMatcher, ...],
    ignored_dirs: frozenset[str],
) -> dict[str, tuple[Path, ...]]:
    supported_paths = {path.resolve() for path in source_files}
    buckets: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.relative_to(root).parts):
            continue
        if any(part in UNSUPPORTED_LANGUAGE_IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.resolve() in supported_paths:
            continue
        suffix = path.suffix
        language = UNSUPPORTED_SOURCE_EXTENSIONS.get(suffix.lower())
        if language is None:
            continue
        if any(_matcher_can_claim(path, suffix, matcher) for matcher in language_files):
            continue
        buckets.setdefault(language, []).append(path)
    return {language: tuple(paths) for language, paths in sorted(buckets.items())}


def _matcher_can_claim(path: Path, suffix: str, matcher: LanguageFileMatcher) -> bool:
    return suffix in matcher.file_extensions or path.name in matcher.manifest_files
