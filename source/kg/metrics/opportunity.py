from __future__ import annotations

"""Typed opportunity detector contract for Debate 19 follow-up PRs."""

from dataclasses import dataclass
from typing import Protocol

from source.kg.core.repo_source import RepoSnapshot


@dataclass(frozen=True)
class Opportunity:
    predicate: str
    source_kind: str
    language_or_format: str
    dimension: str | None
    path: str
    line: int


class OpportunityDetector(Protocol):
    def detect(self, repo: RepoSnapshot, dimension: str | None = None) -> tuple[Opportunity, ...]: ...


__all__ = ["Opportunity", "OpportunityDetector"]
