from __future__ import annotations

from typing import cast

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ScannedFile, iter_scannable_files
from source.kg.extraction.framework.adapter import ExtractionContext


def scannable_config_files(repo: RepoSnapshot, ctx: ExtractionContext) -> list[ScannedFile]:
    key = f"{repo.root}:{repo.commit_sha}"
    cached = ctx.config_scans.get(key)
    if cached is None:
        cached = tuple(iter_scannable_files(repo))
        ctx.config_scans[key] = cached
    return list(cast(tuple[ScannedFile, ...], cached))
