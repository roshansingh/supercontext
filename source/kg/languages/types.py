from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from source.kg.extraction.framework.adapter import Adapter, ExtractionContext


class LanguageFileMatcher(Protocol):
    name: str
    aliases: tuple[str, ...]
    file_extensions: frozenset[str]
    manifest_files: frozenset[str]

    def matches_file(self, path: Path) -> bool: ...


class LanguageSupport(LanguageFileMatcher, Protocol):
    def source_roots(self, repo, ctx: ExtractionContext) -> dict[str, set[str]]: ...

    def parse_repo(self, repo, ctx: ExtractionContext) -> Mapping[str, Any]: ...

    def opportunity_detectors(self) -> tuple[Any, ...]: ...

    def package_resolver(self) -> Any | None: ...

    def dimension_rules(self) -> Mapping[str, Any]: ...

    def useful_edges(self) -> Mapping[str, Any]: ...

    def adapters(self) -> tuple[Adapter, ...]: ...

    def known_stacks(self) -> dict[str, dict[str, str]]: ...
