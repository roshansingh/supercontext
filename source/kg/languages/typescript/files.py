from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TYPESCRIPT_EXTENSIONS = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"})


@dataclass(frozen=True)
class TypeScriptLanguageFiles:
    name: str = "typescript"
    aliases: tuple[str, ...] = ("javascript",)
    file_extensions: frozenset[str] = TYPESCRIPT_EXTENSIONS
    manifest_files: frozenset[str] = frozenset({"package.json", "tsconfig.json"})

    def matches_file(self, path: Path) -> bool:
        if path.name.endswith(".d.ts"):
            return False
        return path.suffix in self.file_extensions


LANGUAGE_FILES = TypeScriptLanguageFiles()
