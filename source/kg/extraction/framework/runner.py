from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import Adapter, AdapterCapability, AdapterResult, ExtractionContext
from source.kg.extraction.framework.allowlists import (
    BYTES_REF_OPTIONAL_SOURCE_SYSTEMS,
    SUPPORTED_ENTITY_KINDS,
    SUPPORTED_FACT_PREDICATES,
)
from source.kg.extraction.framework.known_stacks import KNOWN_STACK_CATEGORY_PREDICATE
from source.kg.metrics.dimension import classify_repo, normalize_package_name


@dataclass(frozen=True)
class SelectedAdapter:
    adapter: Adapter
    capability: AdapterCapability


def run_adapters(
    repo: RepoSnapshot,
    adapters: Iterable[Adapter],
    *,
    strict_extractors: bool = False,
    ctx: ExtractionContext | None = None,
) -> tuple[list[Entity], list[Fact], list[Evidence], list[Coverage], list[JsonObject]]:
    ctx = ctx or ExtractionContext()
    selected_adapters = select_applicable_adapters(repo, adapters, ctx=ctx)
    return run_selected_adapters(repo, selected_adapters, strict_extractors=strict_extractors, ctx=ctx)


def run_selected_adapters(
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
    result_coverage_ids: set[str] = set()
    errors: list[JsonObject] = []
    capabilities: list[AdapterCapability] = []

    for adapter in adapters:
        capability: AdapterCapability | None = None
        try:
            capability = adapter.capability
            _validate_capability(capability)
            capabilities.append(capability)
            result = adapter.extract(repo, ctx)
            _validate(capability, result)
        except Exception as exc:
            errors.append(
                {
                    "adapter": _adapter_name(adapter, capability),
                    "source_system": _adapter_source_system(capability),
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
            coverage.append(_adapter_error_coverage(repo, adapter, capability, ctx, exc))
            continue

        entities.extend(result.entities)
        for fact in result.facts:
            facts_by_id.setdefault(fact.fact_id, fact)
        for row in result.evidence:
            evidence_by_id.setdefault(row.evidence_id, row)
        for row in result.coverage:
            if row.coverage_id in result_coverage_ids:
                continue
            result_coverage_ids.add(row.coverage_id)
            coverage.append(row)

    coverage.extend(_unsupported_known_stack_coverage(repo, ctx, capabilities))

    if strict_extractors and errors:
        raise RuntimeError(_adapter_error_message(repo.name, errors))

    return entities, list(facts_by_id.values()), list(evidence_by_id.values()), coverage, errors


def select_applicable_adapters(
    repo: RepoSnapshot,
    adapters: Iterable[Adapter],
    *,
    ctx: ExtractionContext | None = None,
) -> list[Adapter]:
    return [selection.adapter for selection in select_applicable_adapter_specs(repo, adapters, ctx=ctx)]


def select_applicable_adapter_specs(
    repo: RepoSnapshot,
    adapters: Iterable[Adapter],
    *,
    ctx: ExtractionContext | None = None,
) -> list[SelectedAdapter]:
    ctx = ctx or ExtractionContext()
    repo_languages = _repo_languages(repo)
    selected: list[SelectedAdapter] = []
    for adapter in adapters:
        capability = adapter.capability
        if capability.languages and not set(capability.languages).intersection(repo_languages):
            continue
        if not adapter.applies_to(repo, ctx):
            continue
        selected.append(SelectedAdapter(adapter=adapter, capability=capability))
    return selected


def _repo_languages(repo: RepoSnapshot) -> frozenset[str]:
    languages = {"config"}
    for language in _registered_languages():
        if repo.files_by_language.get(language.name):
            languages.add(language.name)
            languages.update(language.aliases)
    return frozenset(languages)


def _validate(capability: AdapterCapability, result: AdapterResult) -> None:
    for entity in result.entities:
        if entity.kind not in SUPPORTED_ENTITY_KINDS:
            raise ValueError(f"{capability.name} emitted unsupported entity kind: {entity.kind}")
        if capability.produces_entity_kinds and entity.kind not in capability.produces_entity_kinds:
            raise ValueError(f"{capability.name} emitted undeclared entity kind: {entity.kind}")
    for fact in result.facts:
        if fact.predicate not in SUPPORTED_FACT_PREDICATES:
            raise ValueError(f"{capability.name} emitted unsupported predicate: {fact.predicate}")
        if capability.produces_predicates and fact.predicate not in capability.produces_predicates:
            raise ValueError(f"{capability.name} emitted undeclared predicate: {fact.predicate}")
    for row in result.evidence:
        if row.bytes_ref is None and row.source_system not in BYTES_REF_OPTIONAL_SOURCE_SYSTEMS:
            raise ValueError(
                f"{capability.name} emitted evidence without bytes_ref for source_system: {row.source_system}"
            )


def _validate_capability(capability: AdapterCapability) -> None:
    if not capability.source_system:
        raise ValueError(f"{capability.name} must declare source_system")


def _adapter_error_coverage(
    repo: RepoSnapshot,
    adapter: Adapter,
    capability: AdapterCapability | None,
    ctx: ExtractionContext,
    exc: Exception,
) -> Coverage:
    return Coverage(
        tenant_id=ctx.tenant_id,
        predicate="PARSES",
        scope_ref={
            "repo": repo.name,
            "adapter": _adapter_name(adapter, capability),
            "error": type(exc).__name__,
            "message": str(exc),
            "reason": "adapter_error",
        },
        state="uninstrumented",
        source_system=_adapter_source_system(capability),
    )


def _adapter_name(adapter: Adapter, capability: AdapterCapability | None) -> str:
    if capability is not None:
        return capability.name
    return type(adapter).__name__


def _adapter_source_system(capability: AdapterCapability | None) -> str:
    if capability is not None and capability.source_system:
        return capability.source_system
    return "extraction_framework"


def _unsupported_known_stack_coverage(
    repo: RepoSnapshot,
    ctx: ExtractionContext,
    capabilities: list[AdapterCapability],
) -> list[Coverage]:
    supported_tags = {tag for capability in capabilities for tag in capability.framework_tags}
    known_stacks_by_language: dict[str, dict[str, str]] = {}
    registered_languages = _registered_languages()
    for language_support in registered_languages:
        for language, stacks in language_support.known_stacks().items():
            known_stacks_by_language.setdefault(language, {}).update(stacks)
    dimension_scopes = _known_stack_dimension_scopes(repo, registered_languages)

    rows: list[Coverage] = []
    for language_support in registered_languages:
        for language, import_roots in language_support.source_roots(repo, ctx).items():
            rows.extend(
                _known_stack_rows_for_roots(
                    repo,
                    ctx,
                    supported_tags,
                    known_stacks_by_language,
                    dimension_scopes,
                    language,
                    import_roots,
                )
            )
    return rows


def _known_stack_rows_for_roots(
    repo: RepoSnapshot,
    ctx: ExtractionContext,
    supported_tags: set[str],
    known_stacks_by_language: dict[str, dict[str, str]],
    dimension_scopes: dict[tuple[str, str], JsonObject],
    language: str,
    import_roots: set[str],
) -> list[Coverage]:
    rows: list[Coverage] = []
    for import_root in sorted(import_roots):
        category = known_stacks_by_language.get(language, {}).get(import_root)
        if category is None or import_root in supported_tags:
            continue
        predicate = KNOWN_STACK_CATEGORY_PREDICATE.get(category)
        if predicate is None:
            continue
        scope_ref = {
            "repo": repo.name,
            "language": language,
            "import_root": import_root,
            "category": category,
            "reason": "no_adapter_for_known_stack",
        }
        scope_ref.update(dimension_scopes.get((language, normalize_package_name(import_root)), {}))
        rows.append(
            Coverage(
                tenant_id=ctx.tenant_id,
                predicate=predicate,
                scope_ref=scope_ref,
                state="uninstrumented",
                source_system="extraction_framework",
            )
        )
    return rows


def _known_stack_dimension_scopes(
    repo: RepoSnapshot,
    registered_languages: tuple[Any, ...],
) -> dict[tuple[str, str], JsonObject]:
    dimension_languages = tuple(
        language_support
        for language_support in registered_languages
        if callable(getattr(language_support, "dimension_rules", None))
    )
    assignments_by_dimension = {
        assignment.dimension: assignment
        for assignment in classify_repo(repo, dimension_languages)
    }
    scopes: dict[tuple[str, str], JsonObject] = {}
    for language_support in dimension_languages:
        language_names = (language_support.name, *getattr(language_support, "aliases", ()))
        rules_doc = language_support.dimension_rules()
        rules = rules_doc.get("rules", ()) if isinstance(rules_doc, Mapping) else ()
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            dimension = rule.get("dimension")
            if not isinstance(dimension, str):
                continue
            assignment = assignments_by_dimension.get(dimension)
            if assignment is None:
                continue
            scope = {"dimension": dimension, "path_prefix": assignment.path_prefix}
            for stack_name in _dimension_rule_stack_names(rule):
                for language_name in language_names:
                    scopes.setdefault((language_name, stack_name), scope)
    return scopes


def _dimension_rule_stack_names(rule: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for field in ("imports", "packages"):
        values = rule.get(field, ())
        if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
            continue
        names.update(normalize_package_name(value) for value in values if isinstance(value, str))
    return names - {""}


def _registered_languages():
    from source.kg.languages import REGISTERED_LANGUAGES

    return REGISTERED_LANGUAGES


def _adapter_error_message(repo_name: str, errors: list[JsonObject]) -> str:
    details = "; ".join(
        f"{error['source_system']}: {error['error']}: {error['message']}"
        for error in errors
    )
    return f"Extractor errors while indexing {repo_name}: {details}"
