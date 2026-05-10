from __future__ import annotations

from collections.abc import Iterable

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import Adapter, AdapterResult, ExtractionContext
from source.kg.extraction.framework.allowlists import (
    BYTES_REF_OPTIONAL_SOURCE_SYSTEMS,
    SUPPORTED_ENTITY_KINDS,
    SUPPORTED_FACT_PREDICATES,
)


def run_adapters(
    repo: RepoSnapshot,
    adapters: Iterable[Adapter],
    *,
    strict_extractors: bool = False,
    ctx: ExtractionContext | None = None,
) -> tuple[list[Entity], list[Fact], list[Evidence], list[Coverage], list[JsonObject]]:
    ctx = ctx or ExtractionContext()
    entities: list[Entity] = []
    facts_by_id: dict[str, Fact] = {}
    evidence_by_id: dict[str, Evidence] = {}
    coverage: list[Coverage] = []
    errors: list[JsonObject] = []

    for adapter in select_applicable_adapters(repo, adapters, ctx=ctx):
        try:
            result = adapter.extract(repo, ctx)
            _validate(adapter, result)
        except Exception as exc:
            errors.append(
                {
                    "adapter": adapter.capability.name,
                    "source_system": adapter.capability.source_system,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
            coverage.append(_adapter_error_coverage(repo, adapter, ctx, exc))
            continue

        entities.extend(result.entities)
        for fact in result.facts:
            facts_by_id.setdefault(fact.fact_id, fact)
        for row in result.evidence:
            evidence_by_id.setdefault(row.evidence_id, row)
        coverage.extend(result.coverage)

    if strict_extractors and errors:
        raise RuntimeError(_adapter_error_message(repo.name, errors))

    return entities, list(facts_by_id.values()), list(evidence_by_id.values()), coverage, errors


def select_applicable_adapters(
    repo: RepoSnapshot,
    adapters: Iterable[Adapter],
    *,
    ctx: ExtractionContext | None = None,
) -> list[Adapter]:
    ctx = ctx or ExtractionContext()
    repo_languages = _repo_languages(repo)
    selected = []
    for adapter in adapters:
        if adapter.capability.languages and not set(adapter.capability.languages).intersection(repo_languages):
            continue
        if not adapter.applies_to(repo, ctx):
            continue
        selected.append(adapter)
    return selected


def _repo_languages(repo: RepoSnapshot) -> frozenset[str]:
    languages = {"config"}
    if repo.python_files:
        languages.add("python")
    if repo.typescript_files:
        languages.update({"javascript", "typescript"})
    return frozenset(languages)


def _validate(adapter: Adapter, result: AdapterResult) -> None:
    for entity in result.entities:
        if entity.kind not in SUPPORTED_ENTITY_KINDS:
            raise ValueError(f"{adapter.capability.name} emitted unsupported entity kind: {entity.kind}")
        if adapter.capability.produces_entity_kinds and entity.kind not in adapter.capability.produces_entity_kinds:
            raise ValueError(f"{adapter.capability.name} emitted undeclared entity kind: {entity.kind}")
    for fact in result.facts:
        if fact.predicate not in SUPPORTED_FACT_PREDICATES:
            raise ValueError(f"{adapter.capability.name} emitted unsupported predicate: {fact.predicate}")
        if adapter.capability.produces_predicates and fact.predicate not in adapter.capability.produces_predicates:
            raise ValueError(f"{adapter.capability.name} emitted undeclared predicate: {fact.predicate}")
    for row in result.evidence:
        if row.bytes_ref is None and row.source_system not in BYTES_REF_OPTIONAL_SOURCE_SYSTEMS:
            raise ValueError(
                f"{adapter.capability.name} emitted evidence without bytes_ref for source_system: {row.source_system}"
            )


def _adapter_error_coverage(repo: RepoSnapshot, adapter: Adapter, ctx: ExtractionContext, exc: Exception) -> Coverage:
    return Coverage(
        tenant_id=ctx.tenant_id,
        predicate="PARSES",
        scope_ref={
            "repo": repo.name,
            "adapter": adapter.capability.name,
            "error": type(exc).__name__,
            "message": str(exc),
            "reason": "adapter_error",
        },
        state="uninstrumented",
        source_system=adapter.capability.source_system,
    )


def _adapter_error_message(repo_name: str, errors: list[JsonObject]) -> str:
    details = "; ".join(
        f"{error['source_system']}: {error['error']}: {error['message']}"
        for error in errors
    )
    return f"Extractor errors while indexing {repo_name}: {details}"
