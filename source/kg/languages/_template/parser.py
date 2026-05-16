from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import ExtractionContext


def parse_repo(repo: RepoSnapshot, ctx: ExtractionContext) -> Mapping[str, Any]:
    return {}
