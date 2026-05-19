from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from source.kg.extraction.framework.adapter import Adapter, ExtractionContext
    from source.kg.core.repo_source import RepoSnapshot


class LanguageFileMatcher(Protocol):
    name: str
    aliases: tuple[str, ...]
    file_extensions: frozenset[str]
    manifest_files: frozenset[str]

    def matches_file(self, path: Path) -> bool: ...


class PackageMetadata(Protocol):
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None


class PackageResolver(Protocol):
    def manifest_paths(self, repo) -> tuple[Path, ...]: ...

    def package_metadata(self, repo) -> PackageMetadata: ...

    def resolve(self, import_root: str, target_repos: Iterable[Any]) -> str | None: ...


@dataclass(frozen=True)
class ConsumerDependency:
    declared_name: str
    declared_version: str | None
    dependency_kind: str
    manifest_path: Path
    line_number: int | None
    spec_form: Literal["registry", "workspace", "file_path", "git_url", "unknown"]
    target_url: str | None = None


@dataclass(frozen=True)
class ConsumerManifestIssue:
    reason: Literal["cross_repo_dependency_manifest_unreadable"]
    manifest_path: Path
    message: str
    language: str | None = None


@dataclass(frozen=True)
class ConsumerManifestResult:
    dependencies: tuple[ConsumerDependency, ...] = ()
    issues: tuple[ConsumerManifestIssue, ...] = ()


class ConsumerManifestExtractor(Protocol):
    def extract(self, repo: RepoSnapshot) -> ConsumerManifestResult: ...


class LanguageSupport(LanguageFileMatcher, Protocol):
    def source_roots(self, repo, ctx: ExtractionContext) -> dict[str, set[str]]: ...

    def parse_repo(self, repo, ctx: ExtractionContext) -> Mapping[str, Any]: ...

    def opportunity_detectors(self) -> tuple[Any, ...]: ...

    def package_resolver(self) -> PackageResolver | None: ...

    def consumer_manifest_extractor(self) -> ConsumerManifestExtractor | None: ...

    def dimension_rules(self) -> Mapping[str, Any]: ...

    def useful_edges(self) -> Mapping[str, Any]: ...

    def adapters(self) -> tuple[Adapter, ...]: ...

    def known_stacks(self) -> dict[str, dict[str, str]]: ...
