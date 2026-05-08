from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import tomllib

from source.kg.models import Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.pipeline import extract_repo
from source.kg.repo_source import RepoSnapshot, discover_repo
from source.kg.store import JsonlKgStore


LINKER_SOURCE_SYSTEM = "package_linker_v0"
LINKER_RULE_VERSION = "package-linker-v0.1"


@dataclass(frozen=True)
class PackageProvider:
    repo: RepoSnapshot
    package_name: str
    aliases: tuple[str, ...]
    manifest_path: Path | None
    repo_entity_id: str
    service_entity_id: str


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


def build_multi_kg(
    repo_paths: list[str | Path],
    output_dir: str | Path,
    strict_extractors: bool = False,
) -> JsonObject:
    repos = [discover_repo(path) for path in repo_paths]
    build = _build_multi(repos, strict_extractors=strict_extractors)
    manifest: JsonObject = {
        "build_type": "multi_repo",
        "built_at": utc_now_iso(),
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
        },
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


def _build_multi(repos: list[RepoSnapshot], strict_extractors: bool = False) -> MultiRepoBuild:
    entities: list[Entity] = []
    facts: list[Fact] = []
    evidence: list[Evidence] = []
    coverage = []
    extractor_errors: list[JsonObject] = []

    for repo in repos:
        repo_build = extract_repo(repo)
        entities.extend(repo_build.entities)
        facts.extend(repo_build.facts)
        evidence.extend(repo_build.evidence)
        coverage.extend(repo_build.coverage)
        extractor_errors.extend({**error, "repo": repo.name} for error in repo_build.extractor_errors)
    if strict_extractors and extractor_errors:
        raise RuntimeError(_multi_extractor_error_message(extractor_errors))

    providers = _package_providers(repos, entities)
    link_facts, link_evidence, ambiguous_count = _link_external_packages(entities, providers)
    facts.extend(link_facts)
    evidence.extend(link_evidence)
    return MultiRepoBuild(
        entities=entities,
        facts=facts,
        evidence=evidence,
        coverage=coverage,
        extractor_errors=extractor_errors,
        providers=providers,
        link_count=len(link_facts),
        ambiguous_package_count=ambiguous_count,
    )


def _multi_extractor_error_message(extractor_errors: list[JsonObject]) -> str:
    details = "; ".join(
        f"{error['repo']}:{error['source_system']}: {error['error']}: {error['message']}"
        for error in extractor_errors
    )
    return f"Extractor errors while indexing multi-repo snapshot: {details}"


def _package_providers(repos: list[RepoSnapshot], entities: list[Entity]) -> list[PackageProvider]:
    repo_entities: dict[str, Entity] = {}
    service_entities: dict[str, Entity] = {}
    for entity in entities:
        if entity.kind == "Repo":
            repo_entities[str(entity.identity.get("name"))] = entity
        elif entity.kind == "Service":
            repo_name = str(entity.properties.get("repo"))
            service_entities[repo_name] = entity

    providers: list[PackageProvider] = []
    for repo in repos:
        repo_entity = repo_entities.get(repo.name)
        service_entity = service_entities.get(repo.name)
        if repo_entity is None or service_entity is None:
            continue
        package_name, aliases, manifest_path = _package_metadata(repo)
        providers.append(
            PackageProvider(
                repo=repo,
                package_name=package_name,
                aliases=tuple(sorted({alias for alias in aliases if alias})),
                manifest_path=manifest_path,
                repo_entity_id=repo_entity.entity_id,
                service_entity_id=service_entity.entity_id,
            )
        )
    return providers


def _package_metadata(repo: RepoSnapshot) -> tuple[str, set[str], Path | None]:
    pyproject = repo.root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        package_name = str(
            data.get("tool", {}).get("poetry", {}).get("name")
            or data.get("project", {}).get("name")
            or repo.name
        )
        aliases = {package_name, repo.name}
        aliases.update(_python_package_roots(data, repo))
        return package_name, aliases, pyproject

    package_json = repo.root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        package_name = str(data.get("name") or repo.name)
        aliases = {package_name, repo.name, _unscoped_package_name(package_name)}
        return package_name, aliases, package_json

    return repo.name, {repo.name}, None


def _python_package_roots(data: JsonObject, repo: RepoSnapshot) -> set[str]:
    roots = {repo.name}
    for package in data.get("tool", {}).get("poetry", {}).get("packages", []):
        include = package.get("include") if isinstance(package, dict) else None
        if include:
            roots.add(str(include).split(".", 1)[0])
    return roots


def _link_external_packages(
    entities: list[Entity],
    providers: list[PackageProvider],
) -> tuple[list[Fact], list[Evidence], int]:
    provider_index: dict[str, list[PackageProvider]] = {}
    for provider in providers:
        for alias in provider.aliases:
            provider_index.setdefault(_normalize_package_name(alias), []).append(provider)

    facts: list[Fact] = []
    evidence: list[Evidence] = []
    ambiguous_count = 0
    packages_by_id = {entity.entity_id: entity for entity in entities if entity.kind == "ExternalPackage"}
    for package in packages_by_id.values():
        consumer_repo = str(package.identity.get("repo"))
        candidate_names = _external_package_candidate_names(package)
        matches = {
            provider
            for name in candidate_names
            for provider in provider_index.get(_normalize_package_name(name), [])
            if provider.repo.name != consumer_repo
        }
        if not matches:
            continue
        if len(matches) > 1:
            ambiguous_count += 1
            continue
        provider = next(iter(matches))
        matched_name = _matched_name(candidate_names, provider)
        facts.extend(
            [
                Fact(
                    predicate="RESOLVES_TO_REPO",
                    subject_id=package.entity_id,
                    object_id=provider.repo_entity_id,
                    qualifier=_link_qualifier(package, provider, matched_name),
                ),
                Fact(
                    predicate="RESOLVES_TO_SERVICE",
                    subject_id=package.entity_id,
                    object_id=provider.service_entity_id,
                    qualifier=_link_qualifier(package, provider, matched_name),
                ),
            ]
        )
        evidence.extend(_link_evidence(package, provider, facts[-2:]))
    return facts, evidence, ambiguous_count


def _external_package_candidate_names(package: Entity) -> set[str]:
    properties = package.properties
    identity = package.identity
    return {
        str(identity.get("name", "")),
        str(properties.get("import_root", "")),
        str(properties.get("distribution_name", "")),
    } - {""}


def _matched_name(candidate_names: set[str], provider: PackageProvider) -> str:
    provider_names = {_normalize_package_name(alias): alias for alias in provider.aliases}
    for name in sorted(candidate_names):
        if _normalize_package_name(name) in provider_names:
            return name
    return sorted(candidate_names)[0]


def _link_qualifier(package: Entity, provider: PackageProvider, matched_name: str) -> JsonObject:
    return {
        "rule": "unique_normalized_package_name_match",
        "rule_version": LINKER_RULE_VERSION,
        "consumer_repo": package.identity.get("repo"),
        "package_name": package.identity.get("name"),
        "matched_name": matched_name,
        "provider_repo": provider.repo.name,
        "provider_package_name": provider.package_name,
    }


def _link_evidence(package: Entity, provider: PackageProvider, facts: list[Fact]) -> list[Evidence]:
    return [
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
            source_system=LINKER_SOURCE_SYSTEM,
            source_ref={
                "rule": "unique_normalized_package_name_match",
                "rule_version": LINKER_RULE_VERSION,
                "consumer_repo": package.identity.get("repo"),
                "provider_repo": provider.repo.name,
                "provider_package_name": provider.package_name,
            },
            bytes_ref=_manifest_bytes_ref(provider),
            confidence=1.0,
        )
        for fact in facts
    ]


def _manifest_bytes_ref(provider: PackageProvider) -> JsonObject | None:
    if provider.manifest_path is None or not provider.manifest_path.exists():
        return None
    return {
        "repo": provider.repo.name,
        "commit_sha": provider.repo.commit_sha,
        "path": str(provider.manifest_path.relative_to(provider.repo.root)),
        "line_start": 1,
        "line_end": 1,
    }


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _unscoped_package_name(name: str) -> str:
    return name.rsplit("/", 1)[-1] if name.startswith("@") else name
