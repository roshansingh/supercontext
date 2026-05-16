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
    config_scans: dict[str, Any]
    parsed_by_language: dict[str, dict[str, Any]]
    literal_indexes_by_language: dict[str, dict[str, Any]]
    import_roots_by_language: dict[str, set[str]]

    def __init__(
        self,
        tenant_id: str | None = None,
        config_scans: dict[str, Any] | None = None,
        parsed_by_language: dict[str, dict[str, Any]] | None = None,
        literal_indexes_by_language: dict[str, dict[str, Any]] | None = None,
        import_roots_by_language: dict[str, set[str]] | None = None,
        python_parsed_files: dict[str, Any] | None = None,
        python_literal_indexes: dict[str, Any] | None = None,
        js_ts_parsed_files: dict[str, Any] | None = None,
        python_import_roots: set[str] | None = None,
        js_ts_import_roots: set[str] | None = None,
    ) -> None:
        parsed = {language: dict(values) for language, values in (parsed_by_language or {}).items()}
        literal_indexes = {
            language: dict(values) for language, values in (literal_indexes_by_language or {}).items()
        }
        import_roots = {language: set(values) for language, values in (import_roots_by_language or {}).items()}

        if python_parsed_files is not None:
            parsed["python"] = python_parsed_files
        if js_ts_parsed_files is not None:
            parsed["typescript"] = js_ts_parsed_files
        if python_literal_indexes is not None:
            literal_indexes["python"] = python_literal_indexes
        if python_import_roots is not None:
            import_roots["python"] = python_import_roots
        if js_ts_import_roots is not None:
            import_roots["javascript"] = js_ts_import_roots

        object.__setattr__(self, "tenant_id", tenant_id or resolve_tenant_id())
        object.__setattr__(self, "config_scans", config_scans if config_scans is not None else {})
        object.__setattr__(self, "parsed_by_language", parsed)
        object.__setattr__(self, "literal_indexes_by_language", literal_indexes)
        object.__setattr__(self, "import_roots_by_language", import_roots)

    @property
    def python_parsed_files(self) -> dict[str, Any]:
        return self.parsed_by_language.setdefault("python", {})

    @property
    def python_literal_indexes(self) -> dict[str, Any]:
        return self.literal_indexes_by_language.setdefault("python", {})

    @property
    def js_ts_parsed_files(self) -> dict[str, Any]:
        return self.parsed_by_language.setdefault("typescript", {})

    @property
    def python_import_roots(self) -> set[str]:
        return self.import_roots_by_language.setdefault("python", set())

    @property
    def js_ts_import_roots(self) -> set[str]:
        return self.import_roots_by_language.setdefault("javascript", set())


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
