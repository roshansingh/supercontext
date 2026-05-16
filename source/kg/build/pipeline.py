from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import Coverage, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.framework import Adapter, ExtractionContext


def build_kg(
    repo_path: str | Path,
    output_dir: str | Path,
    strict_extractors: bool = False,
    tenant_id: str | None = None,
) -> JsonObject:
    repo = discover_repo(repo_path)
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    build = extract_repo(repo, strict_extractors=strict_extractors, tenant_id=resolved_tenant_id)
    extractor_names = build.extractor_names
    manifest: JsonObject = {
        "repo_path": str(repo.root),
        "repo_name": repo.name,
        "tenant_id": resolved_tenant_id,
        "commit_sha": repo.commit_sha,
        "built_at": utc_now_iso(),
        "extractor": "+".join(extractor_names) if extractor_names else "none",
        "extractors": extractor_names,
        "extractor_errors": build.extractor_errors,
        "counts": {
            "files_by_language": {
                language: len(paths) for language, paths in sorted(repo.files_by_language.items())
            },
            "entities": len({entity.entity_id for entity in build.entities}),
            "facts": len({fact.fact_id for fact in build.facts}),
            "evidence": len({row.evidence_id for row in build.evidence}),
            "coverage": len({row.coverage_id for row in build.coverage}),
        },
    }
    JsonlKgStore(output_dir).write(
        entities=build.entities,
        facts=build.facts,
        evidence=build.evidence,
        coverage=build.coverage,
        manifest=manifest,
    )
    return manifest


@dataclass
class RepoKgBuild:
    entities: list
    facts: list
    evidence: list
    coverage: list[Coverage]
    extractor_names: list[str]
    extractor_errors: list[JsonObject]


def extract_repo(
    repo: RepoSnapshot,
    strict_extractors: bool = False,
    tenant_id: str | None = None,
) -> RepoKgBuild:
    from source.kg.extraction.adapters import REGISTERED_ADAPTERS
    from source.kg.extraction.framework import run_selected_adapters, select_applicable_adapter_specs
    from source.kg.file_formats import file_format_adapters
    from source.kg.languages import language_adapters

    ctx = ExtractionContext(tenant_id=resolve_tenant_id(tenant_id))
    adapters = _combined_adapters(REGISTERED_ADAPTERS, language_adapters(), file_format_adapters())
    selected = select_applicable_adapter_specs(repo, adapters, ctx=ctx)
    selected_adapters = [selection.adapter for selection in selected]
    entities, facts, evidence, coverage, extractor_errors = run_selected_adapters(
        repo,
        selected_adapters,
        strict_extractors=strict_extractors,
        ctx=ctx,
    )
    extractor_names = list(dict.fromkeys(selection.capability.source_system for selection in selected))
    return RepoKgBuild(
        entities=entities,
        facts=facts,
        evidence=evidence,
        coverage=coverage,
        extractor_names=extractor_names,
        extractor_errors=extractor_errors,
    )


def _combined_adapters(*adapter_groups: tuple[Adapter, ...]) -> tuple[Adapter, ...]:
    adapters_by_name: dict[str, Adapter] = {}
    for group in adapter_groups:
        for adapter in group:
            name = adapter.capability.name
            if name in adapters_by_name:
                if adapters_by_name[name] is adapter:
                    continue
                raise ValueError(f"Duplicate adapter name: {name}")
            adapters_by_name[name] = adapter
    return tuple(adapters_by_name.values())
