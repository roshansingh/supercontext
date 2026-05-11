from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from source.kg.build.multi_repo import build_multi, validate_unique_repo_identities
from source.kg.core.models import Coverage, Entity, Evidence, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile, scan_config_files


EXAMPLE_ROOT = Path(__file__).resolve().parent
PrivateExtractor = Callable[[RepoSnapshot, ScannedFile, Entity, ConfigKgBuild, str], None]


def _load_private_extractor(module_name: str, function_name: str) -> PrivateExtractor:
    module_path = EXAMPLE_ROOT / "extractors" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"private_goldset_extractors_{module_name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load private extractor module {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise RuntimeError(f"Private extractor {module_path} does not define callable {function_name}")
    return function


extract_apache_vhost_routes = _load_private_extractor("apache_vhost", "extract_apache_vhost_routes")
extract_zappa_event_sources = _load_private_extractor("zappa", "extract_zappa_event_sources")


PRIVATE_EXTENSION_SOURCE = "private_goldset_extensions_v0"
APACHE_GAP_REASON = "no_oss_adapter_for_apache_vhosts"
ZAPPA_GAP_REASON = "no_oss_adapter_for_zappa_event_sources"
CONFIG_SERVICE_SOURCE_SYSTEMS = {
    "static_config_v0",
    "pyproject_toml",
    "package_json",
    "serverless_yml",
    "zappa_settings_json",
}


@dataclass(frozen=True)
class PrivateExtensionSummary:
    entities: int
    facts: int
    evidence: int
    cleared_coverage: int

    def to_json(self) -> JsonObject:
        return {
            "source_system": PRIVATE_EXTENSION_SOURCE,
            "extractors": ["apache_vhost", "zappa"],
            "entities": self.entities,
            "facts": self.facts,
            "evidence": self.evidence,
            "cleared_coverage": self.cleared_coverage,
        }


def build_private_goldset_kg(
    repo_paths: list[str | Path],
    output_dir: str | Path,
    *,
    tenant_id: str | None = None,
    strict_extractors: bool = False,
) -> JsonObject:
    repos = [discover_repo(path) for path in repo_paths]
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    validate_unique_repo_identities(repos, resolved_tenant_id)
    # Keep rows in memory so private extensions can append and clear superseded coverage before JSONL write.
    build = build_multi(repos, strict_extractors=strict_extractors, tenant_id=resolved_tenant_id)

    summary, cleared_gap_coverage = apply_private_goldset_extensions(
        repos,
        build.entities,
        build.evidence,
        resolved_tenant_id,
    )
    build.entities.extend(summary.entities)
    build.facts.extend(summary.facts)
    build.evidence.extend(summary.evidence)
    build.coverage[:] = _without_satisfied_gap_coverage(build.coverage, cleared_gap_coverage)
    extension_summary = PrivateExtensionSummary(
        entities=len({entity.entity_id for entity in summary.entities}),
        facts=len({fact.fact_id for fact in summary.facts}),
        evidence=len({row.evidence_id for row in summary.evidence}),
        cleared_coverage=len(cleared_gap_coverage),
    )

    manifest: JsonObject = {
        "build_type": "private_goldset_multi_repo",
        "built_at": utc_now_iso(),
        "tenant_id": resolved_tenant_id,
        "repo_count": len(repos),
        "repos": [
            {
                "repo_path": str(repo.root),
                "repo_name": repo.name,
                "owner": repo.owner,
                "commit_sha": repo.commit_sha,
            }
            for repo in repos
        ],
        "linker": {
            "source_system": "package_linker_v0",
            "rule_version": "package-linker-v0.1",
            "provider_count": len(build.providers),
            "link_count": build.link_count,
            "ambiguous_package_count": build.ambiguous_package_count,
        },
        "private_extensions": extension_summary.to_json(),
        "extractor_errors": build.extractor_errors,
        "counts": {
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


def apply_private_goldset_extensions(
    repos: list[RepoSnapshot],
    public_entities: list[Entity],
    public_evidence: list[Evidence],
    tenant_id: str,
) -> tuple[ConfigKgBuild, set[tuple[str, str, str]]]:
    private_build = ConfigKgBuild()
    cleared_gap_coverage: set[tuple[str, str, str]] = set()
    for repo in repos:
        service_entity = _service_entity_for_repo(public_entities, public_evidence, repo, tenant_id)
        for scanned in scan_config_files(repo, tenant_id).files:
            file_build = ConfigKgBuild()
            extract_apache_vhost_routes(repo, scanned, service_entity, file_build, tenant_id)
            extract_zappa_event_sources(repo, scanned, service_entity, file_build, tenant_id)
            private_build.entities.extend(file_build.entities)
            private_build.facts.extend(file_build.facts)
            private_build.evidence.extend(file_build.evidence)
            if any(fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY" for fact in file_build.facts):
                cleared_gap_coverage.add((repo.name, scanned.relative_path, APACHE_GAP_REASON))
            if any(
                fact.predicate == "CONSUMES_EVENT"
                and _fact_has_evidence_from_file(fact.fact_id, file_build, scanned)
                for fact in file_build.facts
            ):
                cleared_gap_coverage.add((repo.name, scanned.relative_path, ZAPPA_GAP_REASON))
    return private_build, cleared_gap_coverage


def _service_entity_for_repo(
    entities: list[Entity],
    evidence: list[Evidence],
    repo: RepoSnapshot,
    tenant_id: str,
) -> Entity:
    matches_by_id = {
        entity.entity_id: entity
        for entity in entities
        if entity.kind == "Service"
        and entity.identity.get("tenant_id") == tenant_id
        and entity.identity.get("repo") == repo.name
    }
    matches = list(matches_by_id.values())
    config_service_ids = {
        row.target_id
        for row in evidence
        if row.target_type == "entity"
        and row.target_id in matches_by_id
        and row.source_system in CONFIG_SERVICE_SOURCE_SYSTEMS
    }
    config_matches = [matches_by_id[entity_id] for entity_id in config_service_ids]
    if len(config_matches) == 1:
        return config_matches[0]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one Service entity for repo {repo.name}; found {len(matches)}")
    return matches[0]


def _fact_has_evidence_from_file(fact_id: str, build: ConfigKgBuild, scanned: ScannedFile) -> bool:
    # Redundant for current per-file extractors; protects future private extractors that emit cross-file facts.
    return any(
        row.target_type == "fact"
        and row.target_id == fact_id
        and row.bytes_ref is not None
        and row.bytes_ref.get("path") == scanned.relative_path
        for row in build.evidence
    )


def _without_satisfied_gap_coverage(
    coverage: list[Coverage],
    cleared_gap_coverage: set[tuple[str, str, str]],
) -> list[Coverage]:
    return [
        row
        for row in coverage
        if (
            str(row.scope_ref.get("repo")),
            str(row.scope_ref.get("file_path")),
            str(row.scope_ref.get("reason")),
        )
        not in cleared_gap_coverage
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a private-goldset KG snapshot with local extension extractors.")
    parser.add_argument("--repo", action="append", required=True, help="Path to an input repository; repeat per repo")
    parser.add_argument("--out", required=True, help="Output directory for the enriched JSONL KG snapshot")
    parser.add_argument("--tenant", help="Tenant id; non-empty value overrides SUPERCONTEXT_TENANT_ID")
    parser.add_argument("--strict-extractors", action="store_true", help="Exit non-zero if any public extractor fails")
    args = parser.parse_args()

    manifest = build_private_goldset_kg(
        args.repo,
        args.out,
        tenant_id=args.tenant,
        strict_extractors=args.strict_extractors,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
