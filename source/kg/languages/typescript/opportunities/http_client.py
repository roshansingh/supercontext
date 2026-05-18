from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo
from source.kg.metrics.opportunity import Opportunity


@dataclass(frozen=True)
class TypeScriptHttpClientOpportunityDetector:
    def detect(self, repo: RepoSnapshot, dimension: str | None = None) -> tuple[Opportunity, ...]:
        if not repo.files_by_language.get("typescript"):
            return ()
        try:
            parsed_files = parse_typescript_repo(repo, None)
        except RuntimeError:
            return ()

        opportunities: list[Opportunity] = []
        for relative_path, parsed_file in parsed_files.items():
            if not isinstance(relative_path, str) or not isinstance(parsed_file, dict):
                continue
            for row in parsed_file.get("client_endpoint_calls", []):
                opportunity = _opportunity_from_row(row, relative_path, dimension)
                if opportunity is not None:
                    opportunities.append(opportunity)
        return tuple(opportunities)


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
