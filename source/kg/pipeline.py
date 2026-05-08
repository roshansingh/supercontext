from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from source.kg.extraction.python.ast_extractor import PythonAstExtractor
from source.kg.models import Coverage, JsonObject, utc_now_iso
from source.kg.repo_source import discover_repo
from source.kg.store import JsonlKgStore
from source.kg.extraction.typescript.compiler_api_extractor import TypeScriptCompilerApiExtractor


def build_kg(repo_path: str | Path, output_dir: str | Path) -> JsonObject:
    repo = discover_repo(repo_path)
    build = extract_repo(repo)
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
    coverage: list
    extractor_names: list[str]
    extractor_errors: list[JsonObject]


def extract_repo(repo) -> RepoKgBuild:
    extractors = []
    if repo.python_files:
        extractors.append(PythonAstExtractor())
    if repo.typescript_files:
        extractors.append(TypeScriptCompilerApiExtractor())

    builds = []
    extractor_errors: list[JsonObject] = []
    for extractor in extractors:
        try:
            builds.append(extractor.extract(repo))
        except Exception as exc:
            extractor_errors.append(
                {
                    "source_system": extractor.source_system,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
    entities = [entity for build in builds for entity in build.entities]
    facts = [fact for build in builds for fact in build.facts]
    evidence = [row for build in builds for row in build.evidence]
    coverage = [row for build in builds for row in build.coverage]
    coverage.extend(
        Coverage(
            tenant_id="local-dev",
            predicate="PARSES",
            scope_ref={
                "repo": repo.name,
                "extractor": error["source_system"],
                "error": error["error"],
                "message": error["message"],
            },
            state="uninstrumented",
            source_system=str(error["source_system"]),
        )
        for error in extractor_errors
    )
    extractor_names = [extractor.source_system for extractor in extractors]
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
