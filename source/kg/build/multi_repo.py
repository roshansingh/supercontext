from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import tomllib

from source.kg.build.pipeline import extract_repo
from source.kg.core.models import Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.core.tenant import resolve_tenant_id


LINKER_SOURCE_SYSTEM = "package_linker_v0"
LINKER_RULE_VERSION = "package-linker-v0.1"


@dataclass(frozen=True)
class RepoIdentity:
    tenant_id: str
    host: str
    owner: str
    name: str

    def to_json(self) -> JsonObject:
        return {"tenant_id": self.tenant_id, "host": self.host, "owner": self.owner, "name": self.name}


@dataclass(frozen=True)
class PackageProvider:
    repo: RepoSnapshot
    repo_identity: RepoIdentity
    package_name: str
    aliases: tuple[str, ...]
    manifest_path: Path | None
    repo_entity_id: str
    service_entity_id: str | None


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
    tenant_id: str | None = None,
) -> JsonObject:
    repos = [discover_repo(path) for path in repo_paths]
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    _validate_unique_repo_identities(repos, resolved_tenant_id)
    build = _build_multi(repos, strict_extractors=strict_extractors, tenant_id=resolved_tenant_id)
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


def _build_multi(
    repos: list[RepoSnapshot],
    strict_extractors: bool = False,
    tenant_id: str | None = None,
) -> MultiRepoBuild:
    entities: list[Entity] = []
    facts: list[Fact] = []
    evidence: list[Evidence] = []
    coverage = []
    extractor_errors: list[JsonObject] = []
    repo_build_entities: list[tuple[RepoSnapshot, list[Entity]]] = []
    entity_repo_identities: dict[str, set[RepoIdentity]] = {}

    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for repo in repos:
        repo_build = extract_repo(repo, tenant_id=resolved_tenant_id)
        repo_identity = _repo_identity(repo, resolved_tenant_id)
        repo_entities = list(repo_build.entities)
        repo_build_entities.append((repo, repo_entities))
        for entity in repo_entities:
            entity_repo_identities.setdefault(entity.entity_id, set()).add(repo_identity)
        entities.extend(repo_build.entities)
        facts.extend(repo_build.facts)
        evidence.extend(repo_build.evidence)
        coverage.extend(repo_build.coverage)
        extractor_errors.extend({**error, "repo": repo.name} for error in repo_build.extractor_errors)
    if strict_extractors and extractor_errors:
        raise RuntimeError(_multi_extractor_error_message(extractor_errors))

    providers = _package_providers(repo_build_entities)
    link_facts, link_evidence, ambiguous_count = _link_external_packages(entities, providers, entity_repo_identities)
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


def _repo_identity(repo: RepoSnapshot, tenant_id: str) -> RepoIdentity:
    # V0 local builds do not preserve git forge host yet; owner/name still
    # prevents same-directory-name repos under different org roots from merging.
    return RepoIdentity(tenant_id=tenant_id, host="local", owner=repo.owner, name=repo.name)


def _validate_unique_repo_identities(repos: list[RepoSnapshot], tenant_id: str) -> None:
    paths_by_identity: dict[RepoIdentity, list[str]] = {}
    for repo in repos:
        paths_by_identity.setdefault(_repo_identity(repo, tenant_id), []).append(str(repo.root))
    duplicates = {identity: paths for identity, paths in paths_by_identity.items() if len(paths) > 1}
    if not duplicates:
        return
    details = "; ".join(
        f"{identity.tenant_id}/{identity.host}/{identity.owner}/{identity.name}: {paths}"
        for identity, paths in sorted(
            duplicates.items(),
            key=lambda item: (item[0].tenant_id, item[0].host, item[0].owner, item[0].name),
        )
    )
    raise ValueError(f"Multi-repo snapshots require unique repo identities. Duplicates: {details}")


def _package_providers(repo_build_entities: list[tuple[RepoSnapshot, list[Entity]]]) -> list[PackageProvider]:
    providers: list[PackageProvider] = []
    for repo, entities in repo_build_entities:
        repo_identity = _repo_identity_from_entities(repo, entities)
        if repo_identity is None:
            continue
        repo_entity = _select_repo_entity(entities, repo_identity)
        if repo_entity is None:
            continue
        service_entities = [entity for entity in entities if entity.kind == "Service"]
        package_name, aliases, manifest_path = _package_metadata(repo)
        service_entity = _select_service_entity(service_entities, aliases)
        providers.append(
            PackageProvider(
                repo=repo,
                repo_identity=repo_identity,
                package_name=package_name,
                aliases=tuple(sorted({alias for alias in aliases if alias})),
                manifest_path=manifest_path,
                repo_entity_id=repo_entity.entity_id,
                service_entity_id=service_entity.entity_id if service_entity else None,
            )
        )
    return providers


def _repo_identity_from_entities(repo: RepoSnapshot, entities: list[Entity]) -> RepoIdentity | None:
    identities = {
        RepoIdentity(
            tenant_id=str(entity.identity.get("tenant_id")),
            host=str(entity.identity.get("host")),
            owner=str(entity.identity.get("owner")),
            name=str(entity.identity.get("name")),
        )
        for entity in entities
        if entity.kind == "Repo"
        and entity.identity.get("owner") == repo.owner
        and entity.identity.get("name") == repo.name
    }
    return next(iter(identities)) if len(identities) == 1 else None


def _select_repo_entity(entities: list[Entity], repo_identity: RepoIdentity) -> Entity | None:
    matches_by_id = {
        entity.entity_id: entity
        for entity in entities
        if entity.kind == "Repo"
        and entity.identity.get("tenant_id") == repo_identity.tenant_id
        and entity.identity.get("host") == repo_identity.host
        and entity.identity.get("owner") == repo_identity.owner
        and entity.identity.get("name") == repo_identity.name
    }
    matches = list(matches_by_id.values())
    return matches[0] if len(matches) == 1 else None


def _select_service_entity(services: list[Entity], aliases: set[str]) -> Entity | None:
    services_by_id = {service.entity_id: service for service in services}
    unique_services = list(services_by_id.values())
    if len(unique_services) == 1:
        return unique_services[0]

    normalized_aliases = {_normalize_package_name(alias) for alias in aliases}
    matches = [
        service
        for service in unique_services
        if _normalize_package_name(str(service.identity.get("slug", ""))) in normalized_aliases
    ]
    return matches[0] if len(matches) == 1 else None


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
    entity_repo_identities: dict[str, set[RepoIdentity]],
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
        consumer_identities = entity_repo_identities.get(package.entity_id, set())
        candidate_names = _external_package_candidate_names(package)
        matches = {
            provider
            for name in candidate_names
            for provider in provider_index.get(_normalize_package_name(name), [])
            if not _is_self_link(provider, consumer_identities)
        }
        if not matches:
            continue
        if len(matches) > 1:
            ambiguous_count += 1
            continue
        provider = next(iter(matches))
        matched_name = _matched_name(candidate_names, provider)
        package_facts = [
            Fact(
                predicate="RESOLVES_TO_REPO",
                subject_id=package.entity_id,
                object_id=provider.repo_entity_id,
                qualifier=_link_qualifier(package, provider, matched_name, consumer_identities),
            )
        ]
        if provider.service_entity_id is not None:
            package_facts.append(
                Fact(
                    predicate="RESOLVES_TO_SERVICE",
                    subject_id=package.entity_id,
                    object_id=provider.service_entity_id,
                    qualifier=_link_qualifier(package, provider, matched_name, consumer_identities),
                )
            )
        facts.extend(package_facts)
        evidence.extend(_link_evidence(package, provider, package_facts, consumer_identities))
    return facts, evidence, ambiguous_count


def _is_self_link(provider: PackageProvider, consumer_identities: set[RepoIdentity]) -> bool:
    if not consumer_identities:
        raise ValueError("ExternalPackage entity missing repo identity tracking")
    return provider.repo_identity in consumer_identities


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


def _link_qualifier(
    package: Entity,
    provider: PackageProvider,
    matched_name: str,
    consumer_identities: set[RepoIdentity],
) -> JsonObject:
    qualifier: JsonObject = {
        "rule": "unique_normalized_package_name_match",
        "rule_version": LINKER_RULE_VERSION,
        "consumer_repo": package.identity.get("repo"),
        "package_name": package.identity.get("name"),
        "matched_name": matched_name,
        "provider_repo": provider.repo.name,
        "provider_repo_identity": provider.repo_identity.to_json(),
        "provider_package_name": provider.package_name,
    }
    if len(consumer_identities) == 1:
        qualifier["consumer_repo_identity"] = next(iter(consumer_identities)).to_json()
    elif len(consumer_identities) > 1:
        qualifier["consumer_repo_identities"] = [
            identity.to_json()
            for identity in _sort_repo_identities(consumer_identities)
        ]
    return qualifier


def _link_evidence(
    package: Entity,
    provider: PackageProvider,
    facts: list[Fact],
    consumer_identities: set[RepoIdentity],
) -> list[Evidence]:
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
                **_consumer_identity_source_ref(consumer_identities),
                "provider_repo": provider.repo.name,
                "provider_repo_identity": provider.repo_identity.to_json(),
                "provider_package_name": provider.package_name,
            },
            bytes_ref=_manifest_bytes_ref(provider),
            confidence=1.0,
        )
        for fact in facts
    ]


def _consumer_identity_source_ref(consumer_identities: set[RepoIdentity]) -> JsonObject:
    if len(consumer_identities) == 1:
        return {"consumer_repo_identity": next(iter(consumer_identities)).to_json()}
    if len(consumer_identities) > 1:
        return {
            "consumer_repo_identities": [
                identity.to_json()
                for identity in _sort_repo_identities(consumer_identities)
            ]
        }
    return {}


def _sort_repo_identities(identities: set[RepoIdentity]) -> list[RepoIdentity]:
    return sorted(identities, key=lambda value: (value.tenant_id, value.host, value.owner, value.name))


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
