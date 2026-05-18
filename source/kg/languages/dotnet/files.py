from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DotnetLanguageFiles:
    name: str = "dotnet"
    aliases: tuple[str, ...] = ("csharp",)
    file_extensions: frozenset[str] = frozenset({".cs"})
    manifest_files: frozenset[str] = frozenset()
    ignored_dirs: frozenset[str] = frozenset({"bin", "obj"})

    def matches_file(self, path: Path) -> bool:
        return path.suffix == ".cs" and not any(part in self.ignored_dirs for part in path.parts)


LANGUAGE_FILES = DotnetLanguageFiles()
