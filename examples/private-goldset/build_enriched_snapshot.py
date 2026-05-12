from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from source.kg.build.multi_repo import build_multi, validate_unique_repo_identities
from source.kg.core.models import JsonObject, utc_now_iso
from source.kg.core.repo_source import discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.core.tenant import resolve_tenant_id


PRIVATE_EXTENSION_SOURCE = "private_goldset_extensions_v0"


@dataclass(frozen=True)
class PrivateExtensionSummary:
    # Retained for manifest compatibility; extractors=[] means the currently
    # judged private-goldset extractors have been promoted into OSS source.
    entities: int
    facts: int
    evidence: int
    cleared_coverage: int

    def to_json(self) -> JsonObject:
        return {
            "source_system": PRIVATE_EXTENSION_SOURCE,
            "extractors": [],
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
    # Keep the private builder as a stable product-validation entry point even
    # when all currently needed extractors have moved into OSS source.
    build = build_multi(repos, strict_extractors=strict_extractors, tenant_id=resolved_tenant_id)
    extension_summary = PrivateExtensionSummary(
        entities=0,
        facts=0,
        evidence=0,
        cleared_coverage=0,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the private-goldset KG snapshot from public OSS extractors.")
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
