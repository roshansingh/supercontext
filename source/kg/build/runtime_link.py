from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject, utc_now_iso
from source.kg.core.repo_source import RepoSnapshot


RUNTIME_LINKER_SOURCE_SYSTEM = "runtime_linker"
RUNTIME_LINKER_RULE_VERSION = "runtime-linker-1"
RUNTIME_LINKS_FILENAME = "cross_repo_runtime_links.jsonl"
RUNTIME_LINK_EVIDENCE_FILENAME = "cross_repo_runtime_link_evidence.jsonl"
RUNTIME_LINK_COVERAGE_FILENAME = "cross_repo_runtime_link_coverage.jsonl"
CROSS_REPO_LINKABLE_DEPLOY_TARGET_TYPES = frozenset(("wsgi",))
DIRECT_DEPLOY_TARGET_TYPES = frozenset(("zappa_lambda",))
SUPPORTED_DEPLOY_TARGET_TYPES = CROSS_REPO_LINKABLE_DEPLOY_TARGET_TYPES | DIRECT_DEPLOY_TARGET_TYPES
_MIN_WSGI_SUFFIX_PARTS = 2


@dataclass(frozen=True)
class RuntimeLinkerInput:
    repo: RepoSnapshot
    entities: tuple[Entity, ...]
    facts: tuple[Fact, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class RuntimeLinkerResult:
    facts: tuple[Fact, ...]
    evidence: tuple[Evidence, ...]
    coverage: tuple[Coverage, ...]
    ambiguous_link_count: int


@dataclass(frozen=True)
class _CodeModuleCandidate:
    service: Entity
    module: Entity
    path: str


@dataclass(frozen=True)
class _RuntimeLinkIssue:
    target: Entity
    reason: str


def link_runtime_targets(inputs: list[RuntimeLinkerInput] | tuple[RuntimeLinkerInput, ...]) -> RuntimeLinkerResult:
    entities = [entity for input_repo in inputs for entity in input_repo.entities]
    facts = [fact for input_repo in inputs for fact in input_repo.facts]
    evidence = [row for input_repo in inputs for row in input_repo.evidence]
    services_by_repo = _services_by_repo(entities)
    module_candidates = _code_module_candidates(entities, services_by_repo)
    existing_deploy_links = {
        (fact.subject_id, fact.object_id)
        for fact in facts
        if fact.predicate == "DEPLOYS_VIA_CONFIG"
    }
    evidence_by_target: dict[str, list[Evidence]] = {}
    for row in evidence:
        evidence_by_target.setdefault(row.target_id, []).append(row)

    deploy_targets = sorted(
        [entity for entity in entities if entity.kind == "DeployTarget"],
        key=lambda entity: (
            str(entity.identity.get("tenant_id", "")),
            str(entity.identity.get("type", "")),
            str(entity.identity.get("target", "")),
            entity.entity_id,
        ),
    )
    emitted: dict[str, Fact] = {}
    emitted_evidence: dict[str, Evidence] = {}
    issues: list[_RuntimeLinkIssue] = []

    for target in deploy_targets:
        target_type = target.identity.get("type")
        if target_type in DIRECT_DEPLOY_TARGET_TYPES:
            continue
        if target_type not in CROSS_REPO_LINKABLE_DEPLOY_TARGET_TYPES:
            issues.append(_RuntimeLinkIssue(target, "unsupported_deploy_target_type"))
            continue
        resolution = _resolve_wsgi_target(target, module_candidates)
        if isinstance(resolution, _RuntimeLinkIssue):
            issues.append(resolution)
            continue
        service = resolution
        if (service.entity_id, target.entity_id) in existing_deploy_links:
            continue
        fact = Fact(
            "DEPLOYS_VIA_CONFIG",
            service.entity_id,
            target.entity_id,
            {
                "source_kind": "runtime_linker",
                "target_type": target_type,
                "resolved_by": "wsgi_longest_unique_module_path_suffix",
                "rule_version": RUNTIME_LINKER_RULE_VERSION,
            },
        )
        evidence_row = _runtime_link_evidence(fact, target, evidence_by_target)
        if evidence_row is None:
            issues.append(_RuntimeLinkIssue(target, "no_target_bytes_ref_evidence"))
            continue
        emitted[fact.fact_id] = fact
        emitted_evidence[evidence_row.evidence_id] = evidence_row

    coverage = tuple(_coverage_rows(inputs, issues))
    return RuntimeLinkerResult(
        facts=tuple(emitted[key] for key in sorted(emitted)),
        evidence=tuple(emitted_evidence[key] for key in sorted(emitted_evidence)),
        coverage=coverage,
        ambiguous_link_count=sum(1 for issue in issues if issue.reason == "ambiguous_wsgi_module_suffix"),
    )


def _services_by_repo(entities: list[Entity]) -> dict[tuple[str, str], list[Entity]]:
    services: dict[tuple[str, str], dict[str, Entity]] = {}
    for entity in entities:
        if entity.kind != "Service":
            continue
        tenant = _non_empty_string(entity.identity.get("tenant_id"))
        repo = _non_empty_string(entity.identity.get("repo")) or _non_empty_string(entity.properties.get("repo"))
        if tenant is None or repo is None:
            continue
        services.setdefault((tenant, repo), {})[entity.entity_id] = entity
    return {key: list(value.values()) for key, value in services.items()}


def _code_module_candidates(
    entities: list[Entity],
    services_by_repo: dict[tuple[str, str], list[Entity]],
) -> list[_CodeModuleCandidate]:
    candidates: list[_CodeModuleCandidate] = []
    for module in entities:
        if module.kind != "CodeModule":
            continue
        tenant = _non_empty_string(module.identity.get("tenant_id"))
        repo = _non_empty_string(module.identity.get("repo"))
        raw_path = _non_empty_string(module.properties.get("path"))
        if tenant is None or repo is None or raw_path is None:
            continue
        services = services_by_repo.get((tenant, repo), [])
        if len(services) != 1:
            continue
        path = _normalize_posix_path(raw_path)
        if path is None:
            continue
        candidates.append(_CodeModuleCandidate(services[0], module, path))
    return candidates


def _resolve_wsgi_target(target: Entity, candidates: list[_CodeModuleCandidate]) -> Entity | _RuntimeLinkIssue:
    tenant = _non_empty_string(target.identity.get("tenant_id"))
    raw_target = _non_empty_string(target.identity.get("target"))
    if tenant is None or raw_target is None:
        return _RuntimeLinkIssue(target, "malformed_deploy_target_identity")
    normalized_target = _normalize_posix_path(raw_target)
    if normalized_target is None:
        return _RuntimeLinkIssue(target, "malformed_deploy_target_path")
    matches = [
        candidate
        for candidate in candidates
        if candidate.service.identity.get("tenant_id") == tenant
        and _is_long_enough_suffix(candidate.path)
        and _path_has_suffix(normalized_target, candidate.path)
    ]
    if not matches:
        return _RuntimeLinkIssue(target, "no_wsgi_module_match")
    max_len = max(len(match.path.split("/")) for match in matches)
    longest = [match for match in matches if len(match.path.split("/")) == max_len]
    service_ids = {match.service.entity_id for match in longest}
    if len(service_ids) != 1:
        return _RuntimeLinkIssue(target, "ambiguous_wsgi_module_suffix")
    return longest[0].service


def _runtime_link_evidence(
    fact: Fact,
    target: Entity,
    evidence_by_target: dict[str, list[Evidence]],
) -> Evidence | None:
    source = _first_coordinate_evidence(evidence_by_target.get(target.entity_id, ()))
    if source is None:
        return None
    return Evidence(
        target_type="fact",
        target_id=fact.fact_id,
        derivation_class="deterministic_static",
        source_system=RUNTIME_LINKER_SOURCE_SYSTEM,
        source_ref={
            "predicate": fact.predicate,
            "rule_version": RUNTIME_LINKER_RULE_VERSION,
            "resolved_by": fact.qualifier.get("resolved_by"),
        },
        bytes_ref=source.bytes_ref,
        confidence=1.0,
    )


def _first_coordinate_evidence(rows: tuple[Evidence, ...] | list[Evidence]) -> Evidence | None:
    for row in rows:
        if row.bytes_ref is not None:
            return row
    return None


def _coverage_rows(
    inputs: list[RuntimeLinkerInput] | tuple[RuntimeLinkerInput, ...],
    issues: list[_RuntimeLinkIssue],
) -> list[Coverage]:
    repos_by_tenant: dict[str, set[str]] = {}
    for input_repo in inputs:
        for entity in input_repo.entities:
            tenant = _non_empty_string(entity.identity.get("tenant_id"))
            repo = _non_empty_string(entity.identity.get("repo")) or _non_empty_string(entity.properties.get("repo"))
            if tenant and repo:
                repos_by_tenant.setdefault(tenant, set()).add(repo)
    rows = [
        Coverage(
            tenant_id=tenant,
            predicate="DEPLOYS_VIA_CONFIG",
            scope_ref={
                "repo_count": len(repos),
                "reason": "runtime_linker_ran",
                "rule_version": RUNTIME_LINKER_RULE_VERSION,
            },
            state="instrumented",
            source_system=RUNTIME_LINKER_SOURCE_SYSTEM,
            checked_at=utc_now_iso(),
        )
        for tenant, repos in sorted(repos_by_tenant.items())
    ]
    for issue in sorted(
        issues,
        key=lambda item: (
            str(item.target.identity.get("tenant_id", "")),
            str(item.target.identity.get("repo", "")),
            str(item.target.identity.get("type", "")),
            str(item.target.identity.get("target", "")),
            item.reason,
        ),
    ):
        tenant = _non_empty_string(issue.target.identity.get("tenant_id")) or "unknown"
        rows.append(
            Coverage(
                tenant_id=tenant,
                predicate="DEPLOYS_VIA_CONFIG",
                scope_ref={
                    "deploy_target_id": issue.target.entity_id,
                    "deploy_target_identity": issue.target.identity,
                    "reason": issue.reason,
                    "rule_version": RUNTIME_LINKER_RULE_VERSION,
                },
                state="partially_instrumented",
                source_system=RUNTIME_LINKER_SOURCE_SYSTEM,
                checked_at=utc_now_iso(),
            )
        )
    return rows


def _normalize_posix_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        return None
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"/", ""}]
    if not parts:
        return None
    return "/".join(parts)


def _path_has_suffix(target_path: str, module_path: str) -> bool:
    return target_path == module_path or target_path.endswith("/" + module_path)


def _is_long_enough_suffix(path: str) -> bool:
    return len(path.split("/")) >= _MIN_WSGI_SUFFIX_PARTS


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
