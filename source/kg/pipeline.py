from __future__ import annotations

from pathlib import Path

from source.kg.models import JsonObject, utc_now_iso
from source.kg.python_ast_extractor import PythonAstExtractor
from source.kg.repo_source import discover_repo
from source.kg.store import JsonlKgStore


def build_python_kg(repo_path: str | Path, output_dir: str | Path) -> JsonObject:
    repo = discover_repo(repo_path)
    extractor = PythonAstExtractor()
    build = extractor.extract(repo)
    manifest: JsonObject = {
        "repo_path": str(repo.root),
        "repo_name": repo.name,
        "commit_sha": repo.commit_sha,
        "built_at": utc_now_iso(),
        "extractor": extractor.source_system,
        "counts": {
            "python_files": len(repo.python_files),
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

