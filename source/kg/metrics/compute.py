from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from math import prod
from pathlib import Path
from typing import Any
import json

import yaml

from source.kg.core.models import JsonObject
from source.kg.core.repo_source import discover_repo
from source.kg.core.store import read_jsonl
from source.kg.extraction.framework.allowlists import SUPPORTED_FACT_PREDICATES
from source.kg.metrics.config import MetricsConfig, load_metrics_config
from source.kg.metrics.dimension import DimensionAssignment, classify_repo
from source.kg.metrics.types import CellMetrics, MetricValue


CORE_SCORE_METRICS = (
    "M_freshness",
    "M_extractor_opportunity",
    "M_evidence_grounding",
    "M_meta_coverage",
    "M_useful_edge",
    "M_trust_mix",
    "M_silent_gap",
    "M_identity_health",
)


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    manifest: JsonObject
    entities: tuple[JsonObject, ...]
    facts: tuple[JsonObject, ...]
    evidence: tuple[JsonObject, ...]
    coverage: tuple[JsonObject, ...]


@dataclass(frozen=True)
class _MetricContext:
    snapshot: _Snapshot
    config: MetricsConfig
    dimension: str | None
    dimension_files: frozenset[str] | None
    is_unclassified_cell: bool
    expected_repos: int | None
    scoped_entities: tuple[JsonObject, ...]
    scoped_facts: tuple[JsonObject, ...]
    scoped_evidence: tuple[JsonObject, ...]


@dataclass(frozen=True)
class _ManifestRepoRef:
    path: str
    identity_keys: tuple[str, ...]
    commit_sha: str


def compute_all(
    snapshot_dir: str | Path,
    *,
    fleet_dir: str | Path | None = None,
    expected_repos: int | None = None,
    config_path: str | Path | None = None,
) -> tuple[CellMetrics, ...]:
    if expected_repos is not None and expected_repos <= 0:
        raise ValueError("expected_repos must be positive when provided")
    snapshot = _read_snapshot(Path(snapshot_dir))
    config = load_metrics_config(Path(config_path) if config_path is not None else None)
    assignments = _dimension_assignments(snapshot)
    has_assignments = bool(assignments)
    cells = assignments or (DimensionAssignment("unknown", ".", tuple(), "no-dimension-detected", "1"),)
    repo_name = _repo_name(snapshot.manifest)
    commit_sha_set = _commit_sha_set(snapshot.manifest)

    results: list[CellMetrics] = []
    for assignment in cells:
        dimension = None if assignment.dimension == "unknown" else assignment.dimension
        dimension_files = None if assignment.dimension == "unknown" else frozenset(assignment.files)
        context = _build_context(
            snapshot,
            config,
            dimension,
            dimension_files,
            expected_repos,
            is_unclassified_cell=not has_assignments,
        )
        metric_values = {
            metric_name: _compute_metric(metric_name, context, fleet_dir=Path(fleet_dir) if fleet_dir else None)
            for metric_name in config.enabled_metrics
        }
        flags = _contract_flags(metric_values)
        results.append(
            CellMetrics(
                repo=repo_name,
                dimension=dimension,
                metric_values=metric_values,
                cell_score=_cell_score(metric_values),
                contract_flags=flags,
                commit_sha_set=commit_sha_set,
            )
        )
    return tuple(results)


def _read_snapshot(snapshot_dir: Path) -> _Snapshot:
    root = snapshot_dir.expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Snapshot manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{manifest_path} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path} must contain a JSON object")

    return _Snapshot(
        path=root,
        manifest=manifest,
        entities=tuple(_read_jsonl_if_exists(root / "entities.jsonl")),
        facts=tuple(_read_jsonl_if_exists(root / "facts.jsonl")),
        evidence=tuple(_read_jsonl_if_exists(root / "evidence.jsonl")),
        coverage=tuple(_read_jsonl_if_exists(root / "coverage.jsonl")),
    )


def _read_jsonl_if_exists(path: Path) -> list[JsonObject]:
    if not path.exists():
        return []
    rows = read_jsonl(path)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
    return rows


def _dimension_assignments(snapshot: _Snapshot) -> tuple[DimensionAssignment, ...]:
    # PR-1 derives dimensions from the current repo_path working tree because
    # snapshots do not persist dimension tags yet. Debate 19 PR-3 moves
    # dimension tags into coverage rows during ingestion.
    assignments: list[DimensionAssignment] = []
    for repo_ref in _manifest_repo_refs(snapshot.manifest):
        root = Path(repo_ref.path).expanduser()
        if not root.exists():
            continue
        try:
            repo = discover_repo(root)
        except OSError:
            continue
        assignments.extend(
            _qualify_assignment_files(assignment, repo_ref.identity_keys, repo_ref.commit_sha)
            for assignment in classify_repo(repo)
        )
    return _merge_assignments(assignments)


def _build_context(
    snapshot: _Snapshot,
    config: MetricsConfig,
    dimension: str | None,
    dimension_files: frozenset[str] | None,
    expected_repos: int | None,
    is_unclassified_cell: bool,
) -> _MetricContext:
    evidence = _scope_evidence(snapshot.evidence, dimension_files)
    evidence_target_ids = {str(row.get("target_id")) for row in evidence}
    entity_ids_from_evidence = {
        str(row.get("target_id"))
        for row in evidence
        if row.get("target_type") == "entity"
    }
    fact_ids_from_evidence = {
        str(row.get("target_id"))
        for row in evidence
        if row.get("target_type") == "fact"
    }
    scoped_entities = tuple(
        entity
        for entity in snapshot.entities
        if dimension_files is None or str(entity.get("entity_id")) in entity_ids_from_evidence
    )
    scoped_entity_ids = {str(entity.get("entity_id")) for entity in scoped_entities}
    scoped_facts = tuple(
        fact
        for fact in snapshot.facts
        if dimension_files is None
        or str(fact.get("fact_id")) in fact_ids_from_evidence
        or str(fact.get("subject_id")) in scoped_entity_ids
        or str(fact.get("object_id")) in scoped_entity_ids
    )
    if dimension_files is not None and not scoped_facts:
        scoped_facts = tuple(fact for fact in snapshot.facts if str(fact.get("fact_id")) in evidence_target_ids)
    return _MetricContext(
        snapshot=snapshot,
        config=config,
        dimension=dimension,
        dimension_files=dimension_files,
        is_unclassified_cell=is_unclassified_cell,
        expected_repos=expected_repos,
        scoped_entities=scoped_entities,
        scoped_facts=scoped_facts,
        scoped_evidence=evidence,
    )


def _scope_evidence(evidence: tuple[JsonObject, ...], dimension_files: frozenset[str] | None) -> tuple[JsonObject, ...]:
    if dimension_files is None:
        return evidence
    return tuple(
        row
        for row in evidence
        if _bytes_ref_scope_key(row.get("bytes_ref")) in dimension_files
    )


def _compute_metric(metric_name: str, context: _MetricContext, *, fleet_dir: Path | None) -> MetricValue:
    if metric_name == "M_inventory":
        return _m_inventory(context)
    if metric_name == "M_dimension_classification":
        return _m_dimension_classification(context)
    if metric_name == "M_freshness":
        return _m_freshness(context)
    if metric_name == "M_extractor_opportunity":
        return MetricValue(0.0, "partial", "no opportunity detectors implemented in PR-1")
    if metric_name == "M_evidence_grounding":
        return _m_evidence_grounding(context)
    if metric_name == "M_meta_coverage":
        return _m_meta_coverage(context)
    if metric_name == "M_silent_gap":
        return MetricValue(0.0, "partial", "no opportunity detectors implemented in PR-1")
    if metric_name == "M_trust_mix":
        return _m_trust_mix(context)
    if metric_name == "M_useful_edge":
        return _m_useful_edge(context)
    if metric_name == "M_cross_repo_linkage":
        return _m_cross_repo_linkage(context, fleet_dir=fleet_dir)
    if metric_name == "M_identity_health":
        return _m_identity_health(context)
    raise ValueError(f"Unsupported metric: {metric_name}")


def _m_inventory(context: _MetricContext) -> MetricValue:
    if context.expected_repos is None:
        return MetricValue(None, "n_a", "missing expected repo denominator")
    actual = _actual_repo_count(context.snapshot.manifest)
    if actual is None:
        return MetricValue(None, "n_a", "missing actual repo count in manifest")
    return MetricValue(min(actual / context.expected_repos, 1.0), "usable")


def _m_dimension_classification(context: _MetricContext) -> MetricValue:
    counts = context.snapshot.manifest.get("counts")
    if not isinstance(counts, dict):
        return MetricValue(None, "n_a", "missing manifest counts.files_by_language denominator")
    manifest_counts = counts.get("files_by_language")
    if not isinstance(manifest_counts, dict):
        return MetricValue(None, "n_a", "missing manifest counts.files_by_language denominator")
    total = 0
    for language, value in manifest_counts.items():
        if not isinstance(language, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return MetricValue(None, "n_a", "malformed manifest counts.files_by_language denominator")
        total += value
    if total <= 0:
        return MetricValue(None, "n_a", "missing manifest counts.files_by_language denominator")
    if context.is_unclassified_cell:
        return MetricValue(0.0, "usable")
    claimed = len(context.dimension_files or ())
    if context.dimension_files is None:
        claimed = total
    return MetricValue(min(claimed / total, 1.0), "usable")


def _m_freshness(context: _MetricContext) -> MetricValue:
    if not context.scoped_evidence:
        return MetricValue(None, "n_a", "no evidence rows")
    cutoff = datetime.now(UTC) - timedelta(days=context.config.freshness_default_days)
    fresh = 0
    parsed = 0
    for row in context.scoped_evidence:
        timestamp = row.get("ingested_at")
        if not isinstance(timestamp, str):
            continue
        try:
            parsed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed_at.tzinfo is None:
            parsed_at = parsed_at.replace(tzinfo=UTC)
        parsed += 1
        if parsed_at >= cutoff:
            fresh += 1
    if parsed == 0:
        return MetricValue(None, "n_a", "no parseable evidence.ingested_at timestamps")
    return MetricValue(fresh / parsed, "usable")


def _m_evidence_grounding(context: _MetricContext) -> MetricValue:
    if not context.scoped_facts:
        return MetricValue(None, "n_a", "no source-backed facts")
    fact_ids = {str(fact.get("fact_id")) for fact in context.scoped_facts}
    fact_evidence = [
        row
        for row in context.snapshot.evidence
        if row.get("target_type") == "fact" and str(row.get("target_id")) in fact_ids
    ]
    grounded_fact_ids = {
        str(row.get("target_id"))
        for row in fact_evidence
        if _valid_bytes_ref(row.get("bytes_ref"))
    }
    value = len(grounded_fact_ids) / len(fact_ids)
    return MetricValue(value, "usable")


def _m_meta_coverage(context: _MetricContext) -> MetricValue:
    entries = _tool_predicate_entries()
    if not entries:
        return MetricValue(None, "n_a", "no tool predicate configuration")
    coverage_predicates = {
        str(row.get("predicate"))
        for row in context.snapshot.coverage
        if row.get("state") in {"instrumented", "partially_instrumented"}
    }
    facts_by_predicate = {str(fact.get("predicate")) for fact in context.scoped_facts}
    covered = sum(1 for predicate in entries if predicate in coverage_predicates or predicate in facts_by_predicate)
    return MetricValue(covered / len(entries), "usable")


def _m_trust_mix(context: _MetricContext) -> MetricValue:
    if not context.scoped_facts:
        return MetricValue(None, "n_a", "no facts in scope")
    evidence_by_fact: dict[str, list[JsonObject]] = {}
    for row in context.snapshot.evidence:
        if row.get("target_type") == "fact":
            evidence_by_fact.setdefault(str(row.get("target_id")), []).append(row)
    scores: list[float] = []
    for fact in context.scoped_facts:
        status_weight = _canonical_status_weight(str(fact.get("canonical_status", "canonical")))
        rows = evidence_by_fact.get(str(fact.get("fact_id")), [])
        if not rows:
            scores.append(0.0)
            continue
        derivation_weight = max(
            context.config.trust_weights.get(str(row.get("derivation_class")), 0.0)
            for row in rows
        )
        scores.append(status_weight * derivation_weight)
    return MetricValue(sum(scores) / len(scores), "usable")


def _m_useful_edge(context: _MetricContext) -> MetricValue:
    specs = _useful_edge_specs_for_dimension(context.dimension)
    if not specs:
        return MetricValue(0.0, "partial", "useful_edges.yaml has no predicates for this dimension")
    if not context.scoped_entities:
        return MetricValue(None, "n_a", "no anchor entities in scope")
    useful_predicates = {spec["predicate"] for spec in specs}
    subject_kinds = {kind for spec in specs for kind in spec["subject_kinds"]}
    useful_subjects = {
        str(fact.get("subject_id"))
        for fact in context.scoped_facts
        if str(fact.get("predicate")) in useful_predicates
    }
    anchors = {
        str(entity.get("entity_id"))
        for entity in context.scoped_entities
        if str(entity.get("kind")) in subject_kinds
    }
    if not anchors:
        return MetricValue(None, "n_a", "no useful-edge anchor entities in scope")
    return MetricValue(len(anchors.intersection(useful_subjects)) / len(anchors), "usable")


def _m_cross_repo_linkage(context: _MetricContext, *, fleet_dir: Path | None) -> MetricValue:
    external_packages = [entity for entity in context.snapshot.entities if entity.get("kind") == "ExternalPackage"]
    if not external_packages:
        return MetricValue(None, "n_a", "no external package imports")
    external_package_ids = {str(entity.get("entity_id")) for entity in external_packages}
    resolved = {
        str(fact.get("subject_id"))
        for fact in context.snapshot.facts
        if fact.get("predicate") == "RESOLVES_TO_REPO"
    }
    value = len(resolved.intersection(external_package_ids)) / len(external_package_ids)
    reason = _linker_stale_reason(context.snapshot, fleet_dir)
    if reason:
        return MetricValue(value, "partial", reason)
    return MetricValue(value, "partial", "package_resolver hooks are not implemented yet")


def _m_identity_health(context: _MetricContext) -> MetricValue:
    if not context.scoped_entities:
        return MetricValue(None, "n_a", "no entities in scope")
    healthy = 0
    for entity in context.scoped_entities:
        urn = entity.get("urn")
        if isinstance(urn, str) and not _looks_like_hash_urn(urn):
            healthy += 1
    return MetricValue(healthy / len(context.scoped_entities), "partial", "per-kind URNs land in Debate 19 PR-4")


def _cell_score(metric_values: dict[str, MetricValue]) -> float | None:
    if not all(metric_name in metric_values for metric_name in CORE_SCORE_METRICS):
        return None
    if any(metric_values[metric_name].state != "usable" for metric_name in CORE_SCORE_METRICS):
        return None
    values = [metric_values[metric_name].value for metric_name in CORE_SCORE_METRICS]
    if any(value is None for value in values):
        return None
    core_values = [
        metric_values["M_freshness"].value,
        metric_values["M_extractor_opportunity"].value,
        metric_values["M_evidence_grounding"].value,
        metric_values["M_meta_coverage"].value,
        metric_values["M_useful_edge"].value,
        metric_values["M_trust_mix"].value,
    ]
    if any(value is None for value in core_values):
        return None
    geomean = prod(max(float(value), 0.0) for value in core_values) ** (1 / len(core_values))
    silent_gap = float(metric_values["M_silent_gap"].value or 0.0)
    identity_health = float(metric_values["M_identity_health"].value or 0.0)
    return geomean * (1 - silent_gap) * identity_health


def _contract_flags(metric_values: dict[str, MetricValue]) -> tuple[str, ...]:
    flags: list[str] = []
    for metric_name, metric_value in sorted(metric_values.items()):
        if metric_value.state == "partial":
            flags.append(f"{metric_name}:partial:{metric_value.reason}")
        elif metric_value.state == "n_a":
            flags.append(f"{metric_name}:n_a:{metric_value.reason}")
        elif metric_name == "M_evidence_grounding" and metric_value.value is not None and metric_value.value < 1.0:
            flags.append("M_evidence_grounding:contract_violation")
        elif metric_name == "M_silent_gap" and metric_value.value is not None and metric_value.value > 0:
            flags.append("M_silent_gap:gap_detected")
    return tuple(flags)


def _actual_repo_count(manifest: JsonObject) -> int | None:
    repos = manifest.get("repos")
    if repos is not None:
        if not isinstance(repos, list) or not repos:
            return None
        for repo in repos:
            if not _valid_manifest_repo_entry(repo, require_owner=True):
                return None
        return len(repos)

    repo_count = manifest.get("repo_count")
    if isinstance(repo_count, int) and not isinstance(repo_count, bool) and repo_count > 0:
        return repo_count

    if _valid_single_repo_manifest(manifest):
        return 1
    return None


def _valid_single_repo_manifest(manifest: JsonObject) -> bool:
    return all(isinstance(manifest.get(field), str) and manifest.get(field) for field in ("repo_path", "repo_name", "commit_sha"))


def _valid_manifest_repo_entry(value: Any, *, require_owner: bool) -> bool:
    if not isinstance(value, dict):
        return False
    required = ("repo_path", "repo_name", "commit_sha", "owner") if require_owner else ("repo_path", "repo_name", "commit_sha")
    return all(isinstance(value.get(field), str) and value.get(field) for field in required)


def _manifest_repo_paths(manifest: JsonObject) -> tuple[str, ...]:
    return tuple(ref.path for ref in _manifest_repo_refs(manifest))


def _manifest_repo_refs(manifest: JsonObject) -> tuple[_ManifestRepoRef, ...]:
    raw_refs: list[tuple[str, str, str, str]] = []
    tenant_id = manifest.get("tenant_id") if isinstance(manifest.get("tenant_id"), str) else "default"
    repo_path = manifest.get("repo_path")
    repo_name = manifest.get("repo_name")
    owner = manifest.get("owner")
    commit_sha = manifest.get("commit_sha")
    if (
        isinstance(repo_path, str)
        and repo_path
        and isinstance(repo_name, str)
        and repo_name
        and isinstance(commit_sha, str)
        and commit_sha
    ):
        identity_key = _manifest_repo_identity_key(tenant_id, owner, repo_name)
        raw_refs.append((repo_path, repo_name, identity_key, commit_sha))
    repos = manifest.get("repos")
    if isinstance(repos, list):
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            nested_path = repo.get("repo_path")
            nested_name = repo.get("repo_name")
            nested_owner = repo.get("owner")
            nested_commit = repo.get("commit_sha")
            if (
                isinstance(nested_path, str)
                and nested_path
                and isinstance(nested_name, str)
                and nested_name
                and isinstance(nested_commit, str)
                and nested_commit
            ):
                identity_key = _manifest_repo_identity_key(tenant_id, nested_owner, nested_name)
                raw_refs.append((nested_path, nested_name, identity_key, nested_commit))
    ambiguous_legacy_keys = _duplicate_legacy_keys(raw_refs)
    deduped: dict[str, _ManifestRepoRef] = {}
    for path, repo_name, identity_key, commit_sha in raw_refs:
        identity_keys = (identity_key,)
        if identity_key != repo_name and (repo_name, commit_sha) not in ambiguous_legacy_keys:
            identity_keys = (identity_key, repo_name)
        ref = _ManifestRepoRef(path, identity_keys, commit_sha)
        deduped.setdefault(ref.path, ref)
    return tuple(deduped.values())


def _duplicate_legacy_keys(raw_refs: list[tuple[str, str, str, str]]) -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for _, repo_name, _, commit_sha in raw_refs:
        key = (repo_name, commit_sha)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def _merge_assignments(assignments: list[DimensionAssignment]) -> tuple[DimensionAssignment, ...]:
    files_by_dimension: dict[str, set[str]] = {}
    rule_ids_by_dimension: dict[str, set[str]] = {}
    versions_by_dimension: dict[str, set[str]] = {}
    for assignment in assignments:
        files_by_dimension.setdefault(assignment.dimension, set()).update(assignment.files)
        rule_ids_by_dimension.setdefault(assignment.dimension, set()).add(assignment.rule_id)
        versions_by_dimension.setdefault(assignment.dimension, set()).add(assignment.rule_version)
    return tuple(
        DimensionAssignment(
            dimension=dimension,
            path_prefix=".",
            files=tuple(sorted(files)),
            rule_id="+".join(sorted(rule_ids_by_dimension.get(dimension, {"unknown-rule"}))),
            rule_version="+".join(sorted(versions_by_dimension.get(dimension, {"1"}))),
        )
        for dimension, files in sorted(files_by_dimension.items())
    )


def _manifest_repo_identity_key(tenant_id: str, owner: Any, name: str) -> str:
    if isinstance(owner, str) and owner:
        return f"{tenant_id}/local/{owner}/{name}"
    return name


def _qualify_assignment_files(assignment: DimensionAssignment, repo_identity_keys: tuple[str, ...], commit_sha: str) -> DimensionAssignment:
    return DimensionAssignment(
        dimension=assignment.dimension,
        path_prefix=assignment.path_prefix,
        files=tuple(
            _file_scope_key(repo_identity_key, commit_sha, path)
            for path in assignment.files
            for repo_identity_key in repo_identity_keys
        ),
        rule_id=assignment.rule_id,
        rule_version=assignment.rule_version,
    )


def _file_scope_key(repo_identity_key: str, commit_sha: str, path: str) -> str:
    return f"{repo_identity_key}@{commit_sha}:{path}"


def _repo_name(manifest: JsonObject) -> str:
    name = manifest.get("repo_name")
    if isinstance(name, str) and name:
        return name
    repos = manifest.get("repos")
    if isinstance(repos, list) and len(repos) == 1 and isinstance(repos[0], dict):
        repo_name = repos[0].get("repo_name")
        if isinstance(repo_name, str) and repo_name:
            return repo_name
    return "__fleet__"


def _commit_sha_set(manifest: JsonObject) -> tuple[str, ...]:
    commit = manifest.get("commit_sha")
    if isinstance(commit, str) and commit:
        return (commit,)
    repos = manifest.get("repos")
    if isinstance(repos, list):
        commits = sorted(
            repo.get("commit_sha")
            for repo in repos
            if isinstance(repo, dict) and isinstance(repo.get("commit_sha"), str)
        )
        return tuple(commits)
    return ()


def _valid_bytes_ref(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required_strings = ("repo", "commit_sha", "path")
    if any(not isinstance(value.get(field), str) or not value.get(field) for field in required_strings):
        return False
    line_start = value.get("line_start")
    line_end = value.get("line_end")
    return (
        isinstance(line_start, int)
        and not isinstance(line_start, bool)
        and isinstance(line_end, int)
        and not isinstance(line_end, bool)
        and line_start > 0
        and line_end >= line_start
    )


def _bytes_ref_path(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    return path if isinstance(path, str) and path else None


def _bytes_ref_scope_key(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    repo_identity_key = _bytes_ref_repo_identity_key(value)
    commit_sha = value.get("commit_sha")
    path = value.get("path")
    if (
        repo_identity_key is None
        or not isinstance(commit_sha, str)
        or not commit_sha
        or not isinstance(path, str)
        or not path
    ):
        return None
    return _file_scope_key(repo_identity_key, commit_sha, path)


def _bytes_ref_repo_identity_key(value: JsonObject) -> str | None:
    repo_identity = value.get("repo_identity")
    if isinstance(repo_identity, dict):
        tenant_id = repo_identity.get("tenant_id")
        host = repo_identity.get("host")
        owner = repo_identity.get("owner")
        name = repo_identity.get("name")
        if all(isinstance(part, str) and part for part in (tenant_id, host, owner, name)):
            return f"{tenant_id}/{host}/{owner}/{name}"
    repo = value.get("repo")
    if isinstance(repo, str) and repo:
        return repo
    return None


@cache
def _tool_predicate_entries() -> tuple[str, ...]:
    path = Path(__file__).with_name("tool_predicates.yaml")
    data = _load_yaml_object(path)
    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise ValueError(f"{path}: tools must be an object")
    predicates: set[str] = set()
    for tool_name, tool_config in tools.items():
        if not isinstance(tool_name, str) or not isinstance(tool_config, dict):
            raise ValueError(f"{path}: each tool entry must be an object")
        raw_predicates = tool_config.get("predicates")
        if not isinstance(raw_predicates, list):
            raise ValueError(f"{path}: tools.{tool_name}.predicates must be a list")
        for predicate in raw_predicates:
            if not isinstance(predicate, str) or not predicate:
                raise ValueError(f"{path}: tools.{tool_name}.predicates entries must be strings")
            predicates.add(predicate)
    return tuple(sorted(predicates))


@cache
def _useful_edge_specs_for_dimension(dimension: str | None) -> tuple[dict[str, tuple[str, ...] | str], ...]:
    path = Path(__file__).with_name("useful_edges.yaml")
    data = _load_yaml_object(path)
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError(f"{path}: dimensions must be an object")
    if dimension is None:
        raw_entries = [
            entry
            for values in dimensions.values()
            if isinstance(values, list)
            for entry in values
        ]
    else:
        raw_entries = dimensions.get(dimension, [])
        if not isinstance(raw_entries, list):
            raise ValueError(f"{path}: dimensions.{dimension} must be a list")
    specs = tuple(_parse_useful_edge_spec(path, entry) for entry in raw_entries)
    unsupported = sorted(
        str(spec["predicate"])
        for spec in specs
        if str(spec["predicate"]) not in SUPPORTED_FACT_PREDICATES
    )
    if unsupported:
        raise ValueError(f"{path}: useful edge predicates must be supported: {unsupported}")
    return specs


def _parse_useful_edge_spec(path: Path, entry: Any) -> dict[str, tuple[str, ...] | str]:
    if not isinstance(entry, dict):
        raise ValueError(f"{path}: useful edge entries must be objects")
    predicate = entry.get("predicate")
    if not isinstance(predicate, str) or not predicate:
        raise ValueError(f"{path}: useful edge predicate must be a non-empty string")
    subject_kinds = entry.get("subject_kinds")
    if not isinstance(subject_kinds, list) or not subject_kinds:
        raise ValueError(f"{path}: useful edge subject_kinds must be a non-empty list")
    parsed_subject_kinds: list[str] = []
    for index, kind in enumerate(subject_kinds):
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"{path}: useful edge subject_kinds[{index}] must be a non-empty string")
        parsed_subject_kinds.append(kind)
    return {"predicate": predicate, "subject_kinds": tuple(parsed_subject_kinds)}


@cache
def _load_yaml_object(path: Path) -> JsonObject:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} could not be parsed as YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _canonical_status_weight(status: str) -> float:
    if status == "canonical":
        return 1.0
    if status == "candidate":
        return 0.5
    if status == "demoted":
        return 0.1
    return 0.0


def _looks_like_hash_urn(urn: str) -> bool:
    # Current Entity.urn uses stable_hash(identity), whose output is 24 hex
    # characters. PR-4 replaces this with per-kind URN templates.
    tail = urn.rsplit("/", 1)[-1]
    return len(tail) == 24 and all(char in "0123456789abcdef" for char in tail)


def _linker_stale_reason(snapshot: _Snapshot, fleet_dir: Path | None) -> str | None:
    if fleet_dir is None:
        return None
    manifest_path = fleet_dir / "_fleet" / "manifest.json"
    if not manifest_path.exists():
        return "linker_stale=true: missing _fleet/manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "linker_stale=true: unparsable _fleet/manifest.json"
    if not isinstance(manifest, dict):
        return "linker_stale=true: malformed _fleet/manifest.json"
    expected_commits = sorted(_commit_sha_set(snapshot.manifest))
    actual_commits = manifest.get("repo_commit_sha_set")
    if not isinstance(actual_commits, list) or sorted(str(commit) for commit in actual_commits) != expected_commits:
        return "linker_stale=true: repo_commit_sha_set mismatch"
    return None
