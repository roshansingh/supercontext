from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.extraction.framework.adapter import Adapter, ExtractionContext
from source.kg.languages._template.files import LANGUAGE_FILES, TemplateLanguageFiles
from source.kg.languages.types import PackageResolver


@dataclass(frozen=True)
class TemplateLanguageSupport:
    files: TemplateLanguageFiles = LANGUAGE_FILES

    @property
    def name(self) -> str:
        return self.files.name

    @property
    def aliases(self) -> tuple[str, ...]:
        return self.files.aliases

    @property
    def file_extensions(self) -> frozenset[str]:
        return self.files.file_extensions

    @property
    def manifest_files(self) -> frozenset[str]:
        return self.files.manifest_files

    def matches_file(self, path: Path) -> bool:
        return self.files.matches_file(path)

    def source_roots(self, repo, ctx: ExtractionContext) -> dict[str, set[str]]:
        return {}

    def parse_repo(self, repo, ctx: ExtractionContext) -> Mapping[str, Any]:
        return {}

    def opportunity_detectors(self) -> tuple[Any, ...]:
        return ()

    def package_resolver(self) -> PackageResolver | None:
        return None

    def dimension_rules(self) -> Mapping[str, Any]:
        return {}

    def useful_edges(self) -> Mapping[str, Any]:
        return {}

    def adapters(self) -> tuple[Adapter, ...]:
        return ()

    def known_stacks(self) -> dict[str, dict[str, str]]:
        return {}


LANGUAGE_SUPPORT = TemplateLanguageSupport()
