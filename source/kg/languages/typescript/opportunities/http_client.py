from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.endpoints import (
    build_typescript_imports_by_local,
    build_typescript_module_clients_index,
    load_typescript_path_aliases,
    resolve_typescript_imported_client,
)
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo
from source.kg.metrics.opportunity import Opportunity


@dataclass(frozen=True)
class TypeScriptHttpClientOpportunityDetector:
    def detect(self, repo: RepoSnapshot, dimension: str | None = None) -> tuple[Opportunity, ...]:
        if not repo.files_by_language.get("typescript"):
            return ()
        parsed_files = parse_typescript_repo(repo, None)

        module_clients = build_typescript_module_clients_index(parsed_files)
        path_aliases = load_typescript_path_aliases(repo.root)
        opportunities: list[Opportunity] = []
        for relative_path, parsed_file in parsed_files.items():
            if not isinstance(relative_path, str) or not isinstance(parsed_file, dict):
                continue
            imports_by_local = build_typescript_imports_by_local(parsed_file)
            for row in parsed_file.get("client_endpoint_calls", []):
                if not _is_confirmed_client_endpoint_row(relative_path, row, imports_by_local, module_clients, path_aliases):
                    continue
                opportunity = _opportunity_from_row(row, relative_path, dimension)
                if opportunity is not None:
                    opportunities.append(opportunity)
        return tuple(opportunities)


def _is_confirmed_client_endpoint_row(
    relative_path: str,
    row: Any,
    imports_by_local: dict[str, dict[str, str]],
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("source_kind") != "imported_axios_call":
        return True
    return resolve_typescript_imported_client(relative_path, row, imports_by_local, module_clients, path_aliases) is not None


def _opportunity_from_row(row: Any, relative_path: str, dimension: str | None) -> Opportunity | None:
    if not isinstance(row, dict):
        return None
    line = row.get("line")
    if isinstance(line, bool) or not isinstance(line, int):
        return None
    source_kind = row.get("source_kind")
    if not isinstance(source_kind, str) or not source_kind:
        return None
    language = _language_or_format(Path(relative_path))
    if language is None:
        return None
    return Opportunity(
        predicate="CALLS_ENDPOINT",
        source_kind=source_kind,
        language_or_format=language,
        dimension=dimension,
        path=relative_path,
        line=line,
    )


def _language_or_format(path: Path) -> str | None:
    if path.suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if path.suffix in {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    return None
