from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters.legacy import LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER
from source.kg.extraction.adapters.typescript_express_routes import TYPESCRIPT_EXPRESS_ROUTES_ADAPTER
from source.kg.extraction.framework.adapter import Adapter, ExtractionContext
from source.kg.extraction.framework.known_stacks import KNOWN_STACK_IMPORTS
from source.kg.extraction.typescript.parser_bridge import parse_typescript_repo
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

    def parse_repo(self, repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, Any]:
        return parse_typescript_repo(repo, ctx)

    def source_roots(self, repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, set[str]]:
        return {"javascript": ctx.js_ts_import_roots}

    def adapters(self) -> tuple[Adapter, ...]:
        return (TYPESCRIPT_EXPRESS_ROUTES_ADAPTER, LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER)

    def opportunity_detectors(self) -> tuple[Any, ...]:
        return ()

    def package_resolver(self) -> Any | None:
        return None

    def dimension_rules(self) -> Mapping[str, Any]:
        return {}

    def useful_edges(self) -> Mapping[str, Any]:
        return {}

    def known_stacks(self) -> Mapping[str, Mapping[str, str]]:
        return {"javascript": KNOWN_STACK_IMPORTS["javascript"]}


LANGUAGE_SUPPORT = TypeScriptLanguageSupport()
