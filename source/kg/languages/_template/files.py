from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemplateLanguageFiles:
    name: str = "_template"
    aliases: tuple[str, ...] = ()
    file_extensions: frozenset[str] = frozenset()
    manifest_files: frozenset[str] = frozenset()

    def matches_file(self, path: Path) -> bool:
        return False


LANGUAGE_FILES = TemplateLanguageFiles()
