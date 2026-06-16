from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from math import prod
from pathlib import Path
from typing import Any, TypedDict
import json

import yaml

from source.kg.core.models import JsonObject
from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.core.store import read_jsonl
from source.kg.extraction.framework.allowlists import SUPPORTED_ENTITY_KINDS, SUPPORTED_FACT_PREDICATES
from source.kg.metrics.config import MetricsConfig, load_metrics_config
from source.kg.metrics.dimension import DimensionAssignment, classify_repo
from source.kg.metrics.opportunity import Opportunity
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
OPPORTUNITY_METRICS = frozenset({"M_extractor_opportunity", "M_silent_gap"})


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    manifest: JsonObject
    entities: tuple[JsonObject, ...]
    facts: tuple[JsonObject, ...]
    evidence: tuple[JsonObject, ...]
    coverage: tuple[JsonObject, ...]
    package_classifications: tuple[JsonObject, ...]


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
    scoped_opportunities: tuple["_ScopedOpportunity", ...]
    fact_evidence_by_predicate: dict[str, tuple[JsonObject, ...]]
    coverage_by_predicate: dict[str, tuple[JsonObject, ...]]


@dataclass(frozen=True)
class _ScopedOpportunity:
    opportunity: Opportunity
    scope_keys: frozenset[str]
    coverage_repos: frozenset[str]


class _UsefulEdgeSpec(TypedDict):
    predicate: str
    subject_kinds: tuple[str, ...]
    object_kinds: tuple[str, ...]


@dataclass(frozen=True)
class _ManifestRepoRef:
    path: str
    identity_keys: tuple[str, ...]
    commit_sha: str


@dataclass(frozen=True)
class _DiscoveredRepoRef:
    manifest_ref: _ManifestRepoRef
    repo: RepoSnapshot


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
    discovered_repos = _discover_manifest_repos(snapshot.manifest)
    assignments = _dimension_assignments(discovered_repos)
    has_assignments = bool(assignments)
    cells = assignments or (DimensionAssignment("unknown", ".", tuple(), "no-dimension-detected", "1"),)
    repo_name = _repo_name(snapshot.manifest)
    commit_sha_set = _commit_sha_set(snapshot.manifest)
    opportunities = (
        _snapshot_opportunities(discovered_repos)
        if OPPORTUNITY_METRICS.intersection(config.enabled_metrics)
        else ()
    )

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
            opportunities,
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
        package_classifications=tuple(_read_package_classifications(root)),
    )


def _read_jsonl_if_exists(path: Path) -> list[JsonObject]:
    if not path.exists():
        return []
    rows = read_jsonl(path)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
    return rows


def _read_package_classifications(root: Path) -> tuple[JsonObject, ...]:
    relink_path = root / "cross_repo_package_classifications.jsonl"
    rows = (
        _read_jsonl_if_exists(relink_path)
        if relink_path.exists()
        else _read_jsonl_if_exists(root / "package_classifications.jsonl")
    )
    _validate_package_classifications(rows, root)
    return tuple(rows)


def _validate_package_classifications(rows: list[JsonObject], root: Path) -> None:
    allowed_buckets = {
        "builtin_or_stdlib",
        "consumer_manifest_external",
        "candidate_internal",
        "candidate_internal_ambiguous",
        "unknown",
    }
    seen: set[str] = set()
    for index, row in enumerate(rows):
        classification_id = row.get("classification_id")
        if not isinstance(classification_id, str) or not classification_id.strip():
            raise ValueError(f"{root}: package classification row {index + 1} classification_id must be non-empty")
        if classification_id != classification_id.strip():
            raise ValueError(f"{root}: package classification row {index + 1} classification_id must not be padded")
        if classification_id in seen:
            raise ValueError(f"{root}: duplicate package classification_id: {classification_id}")
        seen.add(classification_id)
        entity_id = row.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise ValueError(f"{root}: package classification row {index + 1} entity_id must be non-empty")
        if entity_id != entity_id.strip():
            raise ValueError(f"{root}: package classification row {index + 1} entity_id must not be padded")
        package_name = row.get("package_name")
        if "package_name" in row and (not isinstance(package_name, str) or not package_name.strip()):
            raise ValueError(f"{root}: package classification row {index + 1} package_name must be non-empty")
        bucket = row.get("bucket")
        if bucket not in allowed_buckets:
            raise ValueError(f"{root}: package classification row {index + 1} bucket is unsupported: {bucket!r}")


def _discover_manifest_repos(manifest: JsonObject) -> tuple[_DiscoveredRepoRef, ...]:
    discovered: list[_DiscoveredRepoRef] = []
    for repo_ref in _manifest_repo_refs(manifest):
        root = Path(repo_ref.path).expanduser()
        if not root.exists():
            continue
        try:
            repo = discover_repo(root)
        except OSError:
            continue
        discovered.append(_DiscoveredRepoRef(repo_ref, repo))
    return tuple(discovered)


def _dimension_assignments(discovered_repos: tuple[_DiscoveredRepoRef, ...]) -> tuple[DimensionAssignment, ...]:
    # PR-1 derives dimensions from the current repo_path working tree because
    # snapshots do not persist dimension tags yet. Debate 19 PR-3 moves
    # dimension tags into coverage rows during ingestion.
    assignments: list[DimensionAssignment] = []
    for discovered in discovered_repos:
        repo_ref = discovered.manifest_ref
        assignments.extend(
            _qualify_assignment_files(assignment, repo_ref.identity_keys, repo_ref.commit_sha)
            for assignment in classify_repo(discovered.repo)
        )
    return _merge_assignments(assignments)


def _build_context(
    snapshot: _Snapshot,
    config: MetricsConfig,
    dimension: str | None,
    dimension_files: frozenset[str] | None,
    expected_repos: int | None,
    opportunities: tuple[_ScopedOpportunity, ...],
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
    scoped_opportunities = tuple(
        opportunity
        for opportunity in opportunities
        if dimension_files is None or opportunity.scope_keys.intersection(dimension_files)
    )
    fact_evidence_by_predicate = _fact_evidence_by_predicate(scoped_facts, evidence)
    coverage_by_predicate = _rows_by_predicate(snapshot.coverage)
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
        scoped_opportunities=scoped_opportunities,
        fact_evidence_by_predicate=fact_evidence_by_predicate,
        coverage_by_predicate=coverage_by_predicate,
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
        return _m_extractor_opportunity(context)
    if metric_name == "M_evidence_grounding":
        return _m_evidence_grounding(context)
    if metric_name == "M_meta_coverage":
        return _m_meta_coverage(context)
    if metric_name == "M_silent_gap":
        return _m_silent_gap(context)
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
    claimed = _dimension_file_count(context.dimension_files or frozenset())
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


def _m_extractor_opportunity(context: _MetricContext) -> MetricValue:
    if not context.scoped_opportunities:
        return MetricValue(None, "n_a", "no detected opportunities")
    covered = sum(
        1
        for opportunity in context.scoped_opportunities
        if _fact_covers_opportunity(context, opportunity)
    )
    return MetricValue(covered / len(context.scoped_opportunities), "usable")


def _m_silent_gap(context: _MetricContext) -> MetricValue:
    if not context.scoped_opportunities:
        return MetricValue(None, "n_a", "no detected opportunities")
    silent = sum(
        1
        for opportunity in context.scoped_opportunities
        if not _fact_covers_opportunity(context, opportunity)
        and not _coverage_covers_opportunity(context, opportunity)
    )
    return MetricValue(silent / len(context.scoped_opportunities), "usable")


def _m_evidence_grounding(context: _MetricContext) -> MetricValue:
    if not context.scoped_facts:
        return MetricValue(None, "n_a", "no source-backed facts")
    fact_ids = {str(fact.get("fact_id")) for fact in context.scoped_facts}
    fact_evidence = [
        row
        for row in context.scoped_evidence
        if row.get("target_type") == "fact" and str(row.get("target_id")) in fact_ids
    ]
    grounded_fact_ids = {
        str(row.get("target_id"))
        for row in fact_evidence
        if _valid_bytes_ref(row.get("bytes_ref"))
    }
    value = len(grounded_fact_ids) / len(fact_ids)
    return MetricValue(value, "usable")


def _fact_covers_opportunity(context: _MetricContext, scoped_opportunity: _ScopedOpportunity) -> bool:
    opportunity = scoped_opportunity.opportunity
    for row in context.fact_evidence_by_predicate.get(opportunity.predicate, ()):
        bytes_ref = row.get("bytes_ref")
        if _bytes_ref_scope_key(bytes_ref) not in scoped_opportunity.scope_keys:
            continue
        if _line_covers(bytes_ref, opportunity.line):
            return True
    return False


def _coverage_covers_opportunity(context: _MetricContext, scoped_opportunity: _ScopedOpportunity) -> bool:
    opportunity = scoped_opportunity.opportunity
    for row in context.coverage_by_predicate.get(opportunity.predicate, ()):
        # M_silent_gap measures absence of graph facts and absence of explicit
        # coverage. An uninstrumented row is a loud refusal, not a silent gap.
        scope_ref = row.get("scope_ref")
        if not isinstance(scope_ref, dict):
            continue
        repo = scope_ref.get("repo")
        if not isinstance(repo, str) or repo not in scoped_opportunity.coverage_repos:
            continue
        if not _coverage_scope_matches_language(scope_ref, opportunity.language_or_format):
            continue
        if not _coverage_scope_matches_path(scope_ref, opportunity.path):
            continue
        line = scope_ref.get("line")
        if line is None:
            return True
        if isinstance(line, bool) or not isinstance(line, int):
            continue
        if line == opportunity.line:
            return True
    return False


def _fact_evidence_by_predicate(
    scoped_facts: tuple[JsonObject, ...],
    scoped_evidence: tuple[JsonObject, ...],
) -> dict[str, tuple[JsonObject, ...]]:
    predicate_by_fact_id = {
        str(fact.get("fact_id")): str(fact.get("predicate"))
        for fact in scoped_facts
        if isinstance(fact.get("predicate"), str)
    }
    rows_by_predicate: dict[str, list[JsonObject]] = {}
    for row in scoped_evidence:
        if row.get("target_type") != "fact":
            continue
        predicate = predicate_by_fact_id.get(str(row.get("target_id")))
        if predicate is None:
            continue
        rows_by_predicate.setdefault(predicate, []).append(row)
    return {predicate: tuple(rows) for predicate, rows in rows_by_predicate.items()}


def _rows_by_predicate(rows: tuple[JsonObject, ...]) -> dict[str, tuple[JsonObject, ...]]:
    rows_by_predicate: dict[str, list[JsonObject]] = {}
    for row in rows:
        predicate = row.get("predicate")
        if isinstance(predicate, str):
            rows_by_predicate.setdefault(predicate, []).append(row)
    return {predicate: tuple(predicate_rows) for predicate, predicate_rows in rows_by_predicate.items()}


def _coverage_scope_matches_path(scope_ref: JsonObject, opportunity_path: str) -> bool:
    has_path = "file_path" in scope_ref or "path" in scope_ref
    if has_path:
        path = scope_ref.get("file_path", scope_ref.get("path"))
        return isinstance(path, str) and path == opportunity_path
    path_prefix = scope_ref.get("path_prefix")
    if path_prefix is None:
        return True
    if not isinstance(path_prefix, str) or not path_prefix:
        return False
    if path_prefix == ".":
        return True
    normalized = path_prefix.rstrip("/")
    return opportunity_path == normalized or opportunity_path.startswith(f"{normalized}/")


def _coverage_scope_matches_language(scope_ref: JsonObject, opportunity_language: str) -> bool:
    language = scope_ref.get("language")
    if language is None:
        return True
    if not isinstance(language, str) or not language:
        return False
    return opportunity_language in {part.strip() for part in language.split("/") if part.strip()}


def _line_covers(bytes_ref: Any, line: int) -> bool:
    if not isinstance(bytes_ref, dict):
        return False
    line_start = bytes_ref.get("line_start")
    line_end = bytes_ref.get("line_end")
    if not isinstance(line_start, int) or isinstance(line_start, bool):
        return False
    if not isinstance(line_end, int) or isinstance(line_end, bool):
        return False
    return line_start <= line <= line_end


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
    for row in context.scoped_evidence:
        if row.get("target_type") == "fact":
            evidence_by_fact.setdefault(str(row.get("target_id")), []).append(row)
    scores: list[float] = []
    for fact in context.scoped_facts:
        status_weight = _canonical_status_weight(_canonical_status(fact))
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
    subject_specs = {
        (str(spec["predicate"]), kind)
        for spec in specs
        for kind in spec["subject_kinds"]
    }
    object_specs = {
        (str(spec["predicate"]), kind)
        for spec in specs
        for kind in spec["object_kinds"]
    }
    anchor_kinds = {kind for _, kind in subject_specs}.union(kind for _, kind in object_specs)
    snapshot_entity_kinds_by_id = {
        str(entity.get("entity_id")): str(entity.get("kind"))
        for entity in context.snapshot.entities
    }
    scoped_entity_kinds_by_id = {
        str(entity.get("entity_id")): str(entity.get("kind"))
        for entity in context.scoped_entities
    }
    anchors = {
        entity_id
        for entity_id, kind in scoped_entity_kinds_by_id.items()
        if kind in anchor_kinds
    }
    for fact in context.scoped_facts:
        subject_id = str(fact.get("subject_id"))
        object_id = str(fact.get("object_id"))
        subject_kind = snapshot_entity_kinds_by_id.get(subject_id)
        object_kind = snapshot_entity_kinds_by_id.get(object_id)
        if subject_kind in anchor_kinds:
            anchors.add(subject_id)
        if object_kind in anchor_kinds:
            anchors.add(object_id)
    if not anchors:
        return MetricValue(None, "n_a", "no useful-edge anchor entities in scope")
    useful_anchors: set[str] = set()
    for fact in context.scoped_facts:
        if _canonical_status(fact) != "canonical":
            continue
        predicate = str(fact.get("predicate"))
        subject_id = str(fact.get("subject_id"))
        object_id = str(fact.get("object_id"))
        subject_kind = snapshot_entity_kinds_by_id.get(subject_id)
        object_kind = snapshot_entity_kinds_by_id.get(object_id)
        if subject_kind is not None and (predicate, subject_kind) in subject_specs:
            useful_anchors.add(subject_id)
        if object_kind is not None and (predicate, object_kind) in object_specs:
            useful_anchors.add(object_id)
    return MetricValue(len(useful_anchors) / len(anchors), "usable")


def _m_cross_repo_linkage(context: _MetricContext, *, fleet_dir: Path | None) -> MetricValue:
    external_packages = [entity for entity in context.snapshot.entities if entity.get("kind") == "ExternalPackage"]
    if not external_packages:
        return MetricValue(None, "n_a", "no external package imports")
    if context.snapshot.package_classifications:
        ambiguous_ids = {
            str(row.get("entity_id"))
            for row in context.snapshot.package_classifications
            if row.get("bucket") == "candidate_internal_ambiguous"
        }
        candidate_ids = {
            str(row.get("entity_id"))
            for row in context.snapshot.package_classifications
            if row.get("bucket") in {"candidate_internal", "candidate_internal_ambiguous"}
        }
        if not candidate_ids:
            return MetricValue(None, "n_a", "no candidate internal package dependencies")
        resolved = {
            str(fact.get("subject_id"))
            for fact in context.snapshot.facts
            if fact.get("predicate") == "RESOLVES_TO_REPO"
        }
        value = len(resolved.intersection(candidate_ids)) / len(candidate_ids)
        reason = _linker_stale_reason(context.snapshot, fleet_dir)
        if reason:
            return MetricValue(value, "partial", reason)
        resolver_reason = _package_resolver_gap_reason(context.snapshot.manifest)
        if resolver_reason:
            return MetricValue(value, "partial", resolver_reason)
        unresolved_ambiguous_count = len(ambiguous_ids.difference(resolved))
        if unresolved_ambiguous_count:
            return MetricValue(
                value,
                "partial",
                f"{unresolved_ambiguous_count} ambiguous candidate internal package dependencies count as unresolved",
            )
        return MetricValue(value, "usable")
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
    resolver_reason = _package_resolver_gap_reason(context.snapshot.manifest)
    if resolver_reason:
        return MetricValue(value, "partial", resolver_reason)
    return MetricValue(value, "usable")


def _package_resolver_gap_reason(manifest: JsonObject) -> str | None:
    languages = _manifest_source_languages(manifest)
    if not languages:
        return "package_resolver language coverage is unknown"
    missing = []
    for language in _registered_languages():
        language_names = {language.name, *language.aliases}
        if languages.intersection(language_names) and language.package_resolver() is None:
            missing.append(language.name)
    if missing:
        return "package_resolver hooks are not implemented for: " + ", ".join(sorted(missing))
    return None


def _manifest_source_languages(manifest: JsonObject) -> set[str]:
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        return set()
    files_by_language = counts.get("files_by_language")
    if not isinstance(files_by_language, dict):
        return set()
    return {
        language
        for language, count in files_by_language.items()
        if isinstance(language, str) and isinstance(count, int) and not isinstance(count, bool) and count > 0
    }


def _m_identity_health(context: _MetricContext) -> MetricValue:
    if not context.scoped_entities:
        return MetricValue(None, "n_a", "no entities in scope")
    healthy = 0
    for entity in context.scoped_entities:
        urn = entity.get("urn")
        if isinstance(urn, str) and not _looks_like_hash_urn(urn):
            healthy += 1
    return MetricValue(healthy / len(context.scoped_entities), "usable")


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


def _snapshot_opportunities(discovered_repos: tuple[_DiscoveredRepoRef, ...]) -> tuple[_ScopedOpportunity, ...]:
    opportunities: list[_ScopedOpportunity] = []
    detectors = _registered_opportunity_detectors()
    for discovered in discovered_repos:
        repo_ref = discovered.manifest_ref
        for detector in detectors:
            for opportunity in detector.detect(discovered.repo):
                opportunities.append(
                    _ScopedOpportunity(
                        opportunity=opportunity,
                        scope_keys=frozenset(
                            _file_scope_key(repo_identity_key, repo_ref.commit_sha, opportunity.path)
                            for repo_identity_key in repo_ref.identity_keys
                        ),
                        coverage_repos=frozenset(repo_ref.identity_keys),
                    )
                )
    return tuple(opportunities)


def _registered_opportunity_detectors():
    detectors = []
    for language in _registered_languages():
        detectors.extend(language.opportunity_detectors())
    detectors.extend(_registered_file_format_opportunity_detectors())
    return tuple(detectors)


def _registered_file_format_opportunity_detectors():
    from source.kg.file_formats.opportunities import FILE_FORMAT_OPPORTUNITY_DETECTORS

    return FILE_FORMAT_OPPORTUNITY_DETECTORS


def _registered_languages():
    from source.kg.languages import REGISTERED_LANGUAGES

    return REGISTERED_LANGUAGES


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


def _dimension_file_count(dimension_files: frozenset[str]) -> int:
    full_identity_files: set[tuple[str, str, str]] = set()
    legacy_files: set[tuple[str, str, str]] = set()
    full_identity_legacy_aliases: set[tuple[str, str, str]] = set()
    for key in dimension_files:
        parsed = _parse_file_scope_key(key)
        if parsed is None:
            legacy_files.add((key, "", ""))
            continue
        repo_identity_key, commit_sha, path = parsed
        if "/" in repo_identity_key:
            full_identity_files.add((repo_identity_key, commit_sha, path))
            full_identity_legacy_aliases.add((repo_identity_key.rsplit("/", 1)[-1], commit_sha, path))
        else:
            legacy_files.add((repo_identity_key, commit_sha, path))
    return len(full_identity_files) + len(legacy_files - full_identity_legacy_aliases)


def _parse_file_scope_key(key: str) -> tuple[str, str, str] | None:
    identity_and_commit, separator, path = key.partition(":")
    if not separator or not path:
        return None
    repo_identity_key, separator, commit_sha = identity_and_commit.rpartition("@")
    if not separator or not repo_identity_key or not commit_sha:
        return None
    return repo_identity_key, commit_sha, path


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
def _useful_edge_specs_for_dimension(dimension: str | None) -> tuple[_UsefulEdgeSpec, ...]:
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


def _parse_useful_edge_spec(path: Path, entry: Any) -> _UsefulEdgeSpec:
    if not isinstance(entry, dict):
        raise ValueError(f"{path}: useful edge entries must be objects")
    predicate = entry.get("predicate")
    if not isinstance(predicate, str) or not predicate:
        raise ValueError(f"{path}: useful edge predicate must be a non-empty string")
    parsed_subject_kinds = _parse_useful_edge_kinds(path, entry, "subject_kinds")
    parsed_object_kinds = _parse_useful_edge_kinds(path, entry, "object_kinds")
    if not parsed_subject_kinds and not parsed_object_kinds:
        raise ValueError(f"{path}: useful edge entries must define subject_kinds or object_kinds")
    return {
        "predicate": predicate,
        "subject_kinds": tuple(parsed_subject_kinds),
        "object_kinds": tuple(parsed_object_kinds),
    }


def _parse_useful_edge_kinds(path: Path, entry: dict[str, Any], field: str) -> list[str]:
    raw_kinds = entry.get(field, [])
    if not isinstance(raw_kinds, list):
        raise ValueError(f"{path}: useful edge {field} must be a list")
    parsed: list[str] = []
    for index, kind in enumerate(raw_kinds):
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"{path}: useful edge {field}[{index}] must be a non-empty string")
        if kind not in SUPPORTED_ENTITY_KINDS:
            raise ValueError(f"{path}: useful edge {field}[{index}] has unsupported entity kind: {kind}")
        parsed.append(kind)
    return parsed


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


def _canonical_status(row: JsonObject) -> str:
    value = row.get("canonical_status", "canonical")
    return value if isinstance(value, str) and value else "canonical"


def _looks_like_hash_urn(urn: str) -> bool:
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
