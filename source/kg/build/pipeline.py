from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import Coverage, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import JsonlKgStore


def build_kg(repo_path: str | Path, output_dir: str | Path, strict_extractors: bool = False) -> JsonObject:
    repo = discover_repo(repo_path)
    build = extract_repo(repo, strict_extractors=strict_extractors)
    extractor_names = build.extractor_names
    manifest: JsonObject = {
        "repo_path": str(repo.root),
        "repo_name": repo.name,
        "commit_sha": repo.commit_sha,
        "built_at": utc_now_iso(),
        "extractor": "+".join(extractor_names) if extractor_names else "none",
        "extractors": extractor_names,
        "extractor_errors": build.extractor_errors,
        "counts": {
            "python_files": len(repo.python_files),
            "typescript_files": len(repo.typescript_files),
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


def extract_repo(repo: RepoSnapshot, strict_extractors: bool = False) -> RepoKgBuild:
    from source.kg.extraction.adapters import REGISTERED_ADAPTERS
    from source.kg.extraction.framework import run_selected_adapters, select_applicable_adapter_specs

    selected = select_applicable_adapter_specs(repo, REGISTERED_ADAPTERS)
    selected_adapters = [selection.adapter for selection in selected]
    entities, facts, evidence, coverage, extractor_errors = run_selected_adapters(
        repo,
        selected_adapters,
        strict_extractors=strict_extractors,
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


def build_python_kg(repo_path: str | Path, output_dir: str | Path) -> JsonObject:
    return build_kg(repo_path, output_dir)
