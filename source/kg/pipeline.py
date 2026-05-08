from __future__ import annotations

from pathlib import Path

from source.kg.models import JsonObject, utc_now_iso
from source.kg.python_ast_extractor import PythonAstExtractor
from source.kg.repo_source import discover_repo
from source.kg.store import JsonlKgStore
from source.kg.typescript_static_extractor import TypeScriptStaticExtractor


def build_kg(repo_path: str | Path, output_dir: str | Path) -> JsonObject:
    repo = discover_repo(repo_path)
    extractors = []
    if repo.python_files:
        extractors.append(PythonAstExtractor())
    if repo.typescript_files:
        extractors.append(TypeScriptStaticExtractor())

    builds = [extractor.extract(repo) for extractor in extractors]
    entities = [entity for build in builds for entity in build.entities]
    facts = [fact for build in builds for fact in build.facts]
    evidence = [row for build in builds for row in build.evidence]
    coverage = [row for build in builds for row in build.coverage]
    extractor_names = [extractor.source_system for extractor in extractors]
    manifest: JsonObject = {
        "repo_path": str(repo.root),
        "repo_name": repo.name,
        "commit_sha": repo.commit_sha,
        "built_at": utc_now_iso(),
        "extractor": "+".join(extractor_names) if extractor_names else "none",
        "extractors": extractor_names,
        "counts": {
            "python_files": len(repo.python_files),
            "typescript_files": len(repo.typescript_files),
            "entities": len({entity.entity_id for entity in entities}),
            "facts": len({fact.fact_id for fact in facts}),
            "evidence": len({row.evidence_id for row in evidence}),
            "coverage": len({row.coverage_id for row in coverage}),
        },
    }
    JsonlKgStore(output_dir).write(
        entities=entities,
        facts=facts,
        evidence=evidence,
        coverage=coverage,
        manifest=manifest,
    )
    return manifest


def build_python_kg(repo_path: str | Path, output_dir: str | Path) -> JsonObject:
    return build_kg(repo_path, output_dir)
