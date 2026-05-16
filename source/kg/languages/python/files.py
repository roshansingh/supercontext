from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PythonLanguageFiles:
    name: str = "python"
    aliases: tuple[str, ...] = ()
    file_extensions: frozenset[str] = frozenset({".py"})
    manifest_files: frozenset[str] = frozenset({"pyproject.toml", "requirements.txt"})

    def matches_file(self, path: Path) -> bool:
        return path.suffix == ".py"


LANGUAGE_FILES = PythonLanguageFiles()
