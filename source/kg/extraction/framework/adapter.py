from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from source.kg.core.models import Coverage, Entity, Evidence, EvidenceDerivationClass, Fact
from source.kg.core.repo_source import RepoSnapshot


@dataclass(frozen=True)
class AdapterCapability:
    name: str
    languages: tuple[str, ...]
    file_kinds: tuple[str, ...] = ()
    framework_tags: tuple[str, ...] = ()
    produces_predicates: tuple[str, ...] = ()
    produces_entity_kinds: tuple[str, ...] = ()
    ontology_scope: Literal["canonical", "implementation_support", "mixed"] = "canonical"
    derivation_classes: tuple[EvidenceDerivationClass, ...] = ("deterministic_static",)
    default_canonical_status: Literal["canonical", "candidate"] = "canonical"
    source_system: str = ""


@dataclass(frozen=True)
class ExtractionContext:
    tenant_id: str = "local-dev"


@dataclass
class AdapterResult:
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)


class Adapter(Protocol):
    capability: AdapterCapability

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool: ...

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult: ...
