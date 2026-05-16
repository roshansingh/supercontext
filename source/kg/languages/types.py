from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from source.kg.core.repo_source import RepoSnapshot
    from source.kg.extraction.framework.adapter import Adapter, ExtractionContext


KnownStackMap = Mapping[str, str]


class LanguageFileMatcher(Protocol):
    name: str
    aliases: tuple[str, ...]
    file_extensions: frozenset[str]
    manifest_files: frozenset[str]

    def matches_file(self, path: Path) -> bool: ...


class LanguageSupport(LanguageFileMatcher, Protocol):
    def parse_repo(self, repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, Any]: ...

    def source_roots(self, repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, set[str]]: ...

    def adapters(self) -> tuple[Adapter, ...]: ...

    def opportunity_detectors(self) -> tuple[Any, ...]: ...

    def package_resolver(self) -> Any | None: ...

    def dimension_rules(self) -> Mapping[str, Any]: ...

    def useful_edges(self) -> Mapping[str, Any]: ...

    def known_stacks(self) -> Mapping[str, KnownStackMap]: ...
