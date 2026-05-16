from __future__ import annotations

from typing import cast

from source.kg.core.models import Coverage
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.file_formats.common import ConfigScanResult, ScannedFile, scan_config_files
from source.kg.extraction.framework.adapter import ExtractionContext


def config_scan_result(repo: RepoSnapshot, ctx: ExtractionContext) -> ConfigScanResult:
    key = f"{repo.root}:{repo.commit_sha}"
    cached = ctx.config_scans.get(key)
    if cached is None:
        cached = scan_config_files(repo, ctx.tenant_id)
        ctx.config_scans[key] = cached
    return cast(ConfigScanResult, cached)


def scannable_config_files(repo: RepoSnapshot, ctx: ExtractionContext) -> list[ScannedFile]:
    return list(config_scan_result(repo, ctx).files)


def scan_coverage_rows(repo: RepoSnapshot, ctx: ExtractionContext) -> list[Coverage]:
    return list(config_scan_result(repo, ctx).coverage)
