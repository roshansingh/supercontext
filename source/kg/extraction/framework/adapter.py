from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from source.kg.core.models import Coverage, Entity, Evidence, EvidenceDerivationClass, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id


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
    """Shared state for one extraction run.

    Adapters populate import-root sets while extracting; the runner reads them
    after all adapters finish to emit known-stack refusal coverage.
    """

    tenant_id: str = field(default_factory=resolve_tenant_id)
    config_scans: dict[str, tuple[Any, ...]] = field(default_factory=dict, compare=False, repr=False)
    python_parsed_files: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    python_literal_indexes: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    python_import_roots: set[str] = field(default_factory=set, compare=False, repr=False)
    js_ts_import_roots: set[str] = field(default_factory=set, compare=False, repr=False)


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
