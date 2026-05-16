from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import Adapter, ExtractionContext
from source.kg.languages.known_stacks import load_known_stacks
from source.kg.languages.typescript.extractors.legacy_adapter import LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER
from source.kg.languages.typescript.extractors.typescript_express_routes import TYPESCRIPT_EXPRESS_ROUTES_ADAPTER
from source.kg.languages.typescript.files import LANGUAGE_FILES, TypeScriptLanguageFiles


@dataclass(frozen=True)
class TypeScriptLanguageSupport:
    files: TypeScriptLanguageFiles = LANGUAGE_FILES

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

    def source_roots(self, repo: RepoSnapshot, ctx: ExtractionContext) -> dict[str, set[str]]:
        return {"javascript": ctx.import_roots_by_language.setdefault("javascript", set())}

    def parse_repo(self, repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, Any]:
        return {}

    def opportunity_detectors(self) -> tuple[Any, ...]:
        return ()

    def package_resolver(self) -> Any | None:
        return None

    def dimension_rules(self) -> Mapping[str, Any]:
        return {}

    def useful_edges(self) -> Mapping[str, Any]:
        return {}

    def adapters(self) -> tuple[Adapter, ...]:
        return (TYPESCRIPT_EXPRESS_ROUTES_ADAPTER, LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER)

    def known_stacks(self) -> dict[str, dict[str, str]]:
        return {"javascript": dict(_known_stack_imports())}


LANGUAGE_SUPPORT = TypeScriptLanguageSupport()


@cache
def _known_stack_imports() -> dict[str, str]:
    # Static package metadata: read once per process and return copies above.
    return load_known_stacks(Path(__file__).with_name("known_stacks.yaml"))
