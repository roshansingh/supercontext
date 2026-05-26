from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from source.kg.build import relink
from source.kg.build import runtime_link
from source.kg.build.pipeline import extract_repo
from source.kg.core.models import Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.core.tenant import resolve_tenant_id


LINKER_SOURCE_SYSTEM = relink.LINKER_SOURCE_SYSTEM
LINKER_RULE_VERSION = relink.LINKER_RULE_VERSION
RepoIdentity = relink.RepoIdentity
PackageProvider = relink.PackageProvider


@dataclass
class MultiRepoBuild:
    entities: list[Entity]
    facts: list[Fact]
    evidence: list[Evidence]
    coverage: list
    extractor_errors: list[JsonObject]
    providers: list[PackageProvider]
    link_count: int
    ambiguous_package_count: int
    package_classifications: tuple[JsonObject, ...]
    runtime_link_count: int
    runtime_ambiguous_link_count: int
    support_facts: list[Fact] = field(default_factory=list)


def build_multi_kg(
    repo_paths: list[str | Path],
    output_dir: str | Path,
    strict_extractors: bool = False,
    tenant_id: str | None = None,
) -> JsonObject:
    repos = [discover_repo(path) for path in repo_paths]
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    validate_unique_repo_identities(repos, resolved_tenant_id)
    build = build_multi(repos, strict_extractors=strict_extractors, tenant_id=resolved_tenant_id)
    manifest: JsonObject = {
        "build_type": "multi_repo",
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
            "source_system": LINKER_SOURCE_SYSTEM,
            "rule_version": LINKER_RULE_VERSION,
            "provider_count": len(build.providers),
            "link_count": build.link_count,
            "ambiguous_package_count": build.ambiguous_package_count,
            "package_classification_count": len(build.package_classifications),
        },
        "runtime_linker": {
            "source_system": runtime_link.RUNTIME_LINKER_SOURCE_SYSTEM,
            "rule_version": runtime_link.RUNTIME_LINKER_RULE_VERSION,
            "link_count": build.runtime_link_count,
            "ambiguous_link_count": build.runtime_ambiguous_link_count,
        },
        "extractor_errors": build.extractor_errors,
        "counts": {
            "files_by_language": _files_by_language_counts(repos),
            "unsupported_files_by_language": _unsupported_files_by_language_counts(repos),
            "entities": len({entity.entity_id for entity in build.entities}),
            "facts": len({fact.fact_id for fact in build.facts}),
            "support_facts": len({fact.fact_id for fact in build.support_facts}),
            "evidence": len({row.evidence_id for row in build.evidence}),
            "coverage": len({row.coverage_id for row in build.coverage}),
        },
    }
    JsonlKgStore(output_dir).write(
        entities=build.entities,
        facts=build.facts,
        support_facts=build.support_facts,
        evidence=build.evidence,
        coverage=build.coverage,
        manifest=manifest,
    )
    relink.write_package_classifications(output_dir, build.package_classifications)
    return manifest


def build_multi(
    repos: list[RepoSnapshot],
    strict_extractors: bool = False,
    tenant_id: str | None = None,
) -> MultiRepoBuild:
    entities: list[Entity] = []
    facts: list[Fact] = []
    support_facts: list[Fact] = []
    evidence: list[Evidence] = []
    coverage = []
    extractor_errors: list[JsonObject] = []
    linker_inputs: list[relink.LinkerInput] = []
    runtime_inputs: list[runtime_link.RuntimeLinkerInput] = []

    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for repo in repos:
        repo_build = extract_repo(repo, tenant_id=resolved_tenant_id)
        repo_identity = relink.repo_identity(repo, resolved_tenant_id)
        repo_entities = list(repo_build.entities)
        repo_facts = list(repo_build.facts)
        repo_evidence = relink.repo_identity_evidence(repo_build.evidence, repo, repo_identity)
        linker_inputs.append(relink.LinkerInput(repo, repo_identity, tuple(repo_entities), tuple(repo_facts), tuple(repo_evidence)))
        runtime_inputs.append(runtime_link.RuntimeLinkerInput(repo, tuple(repo_entities), tuple(repo_facts), tuple(repo_evidence)))
        entities.extend(repo_build.entities)
        facts.extend(repo_build.facts)
        support_facts.extend(repo_build.support_facts)
        evidence.extend(repo_evidence)
        coverage.extend(repo_build.coverage)
        extractor_errors.extend(
            {
                **error,
                "repo": relink.repo_identity_key(repo_identity),
                "repo_name": repo.name,
                "repo_identity": repo_identity.to_json(),
                "repo_root": str(repo.root),
            }
            for error in repo_build.extractor_errors
        )
    if strict_extractors and extractor_errors:
        raise RuntimeError(_multi_extractor_error_message(extractor_errors))

    link_result = relink.link_external_packages(linker_inputs)
    runtime_result = runtime_link.link_runtime_targets(runtime_inputs)
    facts.extend(link_result.facts)
    facts.extend(runtime_result.facts)
    evidence.extend(link_result.evidence)
    evidence.extend(runtime_result.evidence)
    coverage.extend(link_result.coverage)
    coverage.extend(runtime_result.coverage)
    return MultiRepoBuild(
        entities=entities,
        facts=facts,
        support_facts=support_facts,
        evidence=evidence,
        coverage=coverage,
        extractor_errors=extractor_errors,
        providers=list(link_result.providers),
        link_count=len(link_result.facts),
        ambiguous_package_count=link_result.ambiguous_package_count,
        package_classifications=link_result.package_classifications,
        runtime_link_count=len(runtime_result.facts),
        runtime_ambiguous_link_count=runtime_result.ambiguous_link_count,
    )


def _files_by_language_counts(repos: list[RepoSnapshot]) -> JsonObject:
    counts: dict[str, int] = {}
    for repo in repos:
        for language, paths in repo.files_by_language.items():
            counts[language] = counts.get(language, 0) + len(paths)
    return dict(sorted(counts.items()))


def _unsupported_files_by_language_counts(repos: list[RepoSnapshot]) -> JsonObject:
    counts: dict[str, int] = {}
    for repo in repos:
        for language, paths in repo.unsupported_files_by_language.items():
            counts[language] = counts.get(language, 0) + len(paths)
    return dict(sorted(counts.items()))


def _multi_extractor_error_message(extractor_errors: list[JsonObject]) -> str:
    details = "; ".join(
        f"{error['repo']}:{error['source_system']}: {error['error']}: {error['message']}"
        for error in extractor_errors
    )
    return f"Extractor errors while indexing multi-repo snapshot: {details}"


def validate_unique_repo_identities(repos: list[RepoSnapshot], tenant_id: str) -> None:
    relink.validate_unique_repo_identities(repos, tenant_id)
