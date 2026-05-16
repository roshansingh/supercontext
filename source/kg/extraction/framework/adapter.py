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


@dataclass(frozen=True, init=False, eq=False)
class ExtractionContext:
    """Shared state for one extraction run.

    Adapters populate import-root sets while extracting; the runner reads them
    after all adapters finish to emit known-stack refusal coverage.
    """

    tenant_id: str
    config_scans: dict[str, Any] = field(compare=False, repr=False)
    parsed_by_language: dict[str, dict[str, Any]] = field(compare=False, repr=False)
    literal_indexes_by_language: dict[str, dict[str, Any]] = field(compare=False, repr=False)
    import_roots_by_language: dict[str, set[str]] = field(compare=False, repr=False)

    def __init__(
        self,
        tenant_id: str | None = None,
        config_scans: dict[str, Any] | None = None,
        parsed_by_language: dict[str, dict[str, Any]] | None = None,
        literal_indexes_by_language: dict[str, dict[str, Any]] | None = None,
        import_roots_by_language: dict[str, set[str]] | None = None,
    ) -> None:
        parsed = {language: dict(values) for language, values in (parsed_by_language or {}).items()}
        literal_indexes = {
            language: dict(values) for language, values in (literal_indexes_by_language or {}).items()
        }
        import_roots = {language: set(values) for language, values in (import_roots_by_language or {}).items()}

        object.__setattr__(self, "tenant_id", tenant_id or resolve_tenant_id())
        object.__setattr__(self, "config_scans", config_scans if config_scans is not None else {})
        object.__setattr__(self, "parsed_by_language", parsed)
        object.__setattr__(self, "literal_indexes_by_language", literal_indexes)
        object.__setattr__(self, "import_roots_by_language", import_roots)


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
