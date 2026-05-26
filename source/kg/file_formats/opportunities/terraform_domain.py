from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

from source.kg.core.models import Entity
from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats._shared.common import ConfigKgBuild, MAX_SCAN_BYTES, ScannedFile
from source.kg.file_formats.terraform import extract_terraform_files
from source.kg.metrics.opportunity import Opportunity


@dataclass(frozen=True)
class TerraformDomainOpportunityDetector:
    def detect(self, repo: RepoSnapshot, dimension: str | None = None) -> tuple[Opportunity, ...]:
        build = ConfigKgBuild()
        tenant_id = resolve_tenant_id()
        service = Entity(
            kind="Service",
            identity={"tenant_id": tenant_id, "namespace": "default", "repo": repo.name, "slug": repo.name},
        )
        terraform_files = _scan_terraform_files(repo)
        if not terraform_files:
            return ()
        extract_terraform_files(repo, terraform_files, service, build, tenant_id)

        source_kind_by_fact_id = {
            fact.fact_id: fact.qualifier.get("source_kind")
            for fact in build.facts
            if fact.predicate == "REFERENCES_DOMAIN"
        }
        opportunities: list[Opportunity] = []
        seen: set[tuple[str, int, str]] = set()
        for row in build.evidence:
            if row.target_type != "fact" or row.target_id not in source_kind_by_fact_id:
                continue
            opportunity = _opportunity_from_evidence(row.bytes_ref, source_kind_by_fact_id[row.target_id], dimension)
            if opportunity is None:
                continue
            key = (opportunity.path, opportunity.line, opportunity.source_kind)
            if key in seen:
                continue
            seen.add(key)
            opportunities.append(opportunity)
        return tuple(opportunities)


def _opportunity_from_evidence(bytes_ref: Any, source_kind: Any, dimension: str | None) -> Opportunity | None:
    if not isinstance(bytes_ref, dict):
        return None
    if not isinstance(source_kind, str) or not source_kind:
        return None
    path = bytes_ref.get("path")
    line = bytes_ref.get("line_start")
    if not isinstance(path, str) or not path:
        return None
    if isinstance(line, bool) or not isinstance(line, int):
        return None
    return Opportunity(
        predicate="REFERENCES_DOMAIN",
        source_kind=source_kind,
        language_or_format="terraform",
        dimension=dimension,
        path=path,
        line=line,
    )


def _scan_terraform_files(repo: RepoSnapshot) -> tuple[ScannedFile, ...]:
    files: list[ScannedFile] = []
    for dirpath, dirnames, filenames in os.walk(repo.root):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if path.suffix != ".tf":
                continue
            try:
                if path.stat().st_size > MAX_SCAN_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files.append(
                ScannedFile(
                    path=path,
                    relative_path=str(path.relative_to(repo.root)),
                    text=text,
                    lines=tuple(text.splitlines()),
                )
            )
    return tuple(files)
