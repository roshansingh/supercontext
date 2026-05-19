from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from source.kg.core.models import JsonObject
from source.kg.core.store import read_jsonl
from source.kg.metrics.constants import METRICS_FILENAME


REPORT_JSON_FILENAME = "coverage-run.json"
REPORT_MARKDOWN_FILENAME = "coverage-run.md"
# Keep this aligned with source/kg/metrics/config.yaml metric semantics.
LOWER_IS_BETTER_METRICS = frozenset({"M_silent_gap"})


@dataclass(frozen=True)
class CoverageReport:
    json_path: Path
    markdown_path: Path
    payload: JsonObject


def write_coverage_report(
    snapshot_dir: str | Path,
    output_dir: str | Path,
    *,
    run_id: str | None = None,
    expected_repos: int | None = None,
    tenant: str | None = None,
    metric_config: str | None = None,
) -> CoverageReport:
    snapshot = Path(snapshot_dir).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    if expected_repos is not None and expected_repos <= 0:
        raise ValueError("expected_repos must be positive when provided")
    manifest = _read_manifest(snapshot)
    metrics = _read_metrics(snapshot)
    coverage = _read_coverage(snapshot)
    package_classifications = _read_package_classifications(snapshot)
    payload = build_coverage_report_payload(
        snapshot,
        manifest,
        metrics,
        coverage,
        package_classifications,
        run_id=run_id,
        expected_repos=expected_repos,
        tenant=tenant,
        metric_config=metric_config,
    )
    markdown = render_coverage_report_markdown(payload)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / REPORT_JSON_FILENAME
    markdown_path = out / REPORT_MARKDOWN_FILENAME
    _atomic_write_text(json_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write_text(markdown_path, markdown)
    return CoverageReport(json_path=json_path, markdown_path=markdown_path, payload=payload)


def build_coverage_report_payload(
    snapshot_dir: Path,
    manifest: JsonObject,
    metrics: tuple[JsonObject, ...],
    coverage: tuple[JsonObject, ...] = (),
    package_classifications: tuple[JsonObject, ...] = (),
    *,
    run_id: str | None = None,
    expected_repos: int | None = None,
    tenant: str | None = None,
    metric_config: str | None = None,
) -> JsonObject:
    cells = tuple(
        sorted(
            (_cell_payload(row) for row in metrics),
            key=lambda cell: (str(cell["repo"]), str(cell["dimension"] or "")),
        )
    )
    coverage_gaps = _coverage_gaps(manifest, coverage)
    return {
        "schema_version": 1,
        "run_id": run_id or snapshot_dir.name,
        "tenant": tenant or _tenant(manifest),
        "snapshot_dir": str(snapshot_dir),
        "snapshot_built_at": manifest.get("built_at") if isinstance(manifest.get("built_at"), str) else None,
        "metrics_built_at_set": _metrics_built_at_set(metrics),
        "metric_config": metric_config,
        "repo_count_expected": expected_repos,
        "repo_count_indexed": _repo_count(manifest),
        "summary": _summary(cells, coverage_gaps),
        "package_classification_summary": _package_classification_summary(package_classifications),
        "coverage_gaps": coverage_gaps,
        "cells": list(cells),
    }


def render_coverage_report_markdown(payload: JsonObject) -> str:
    summary = payload["summary"]
    lines = [
        f"# Coverage Run: {payload['run_id']}",
        "",
        f"- Tenant: `{_markdown_code(payload['tenant'])}`",
        f"- Snapshot: `{_markdown_code(payload['snapshot_dir'])}`",
        f"- Indexed repos: `{payload['repo_count_indexed']}`",
        f"- Expected repos: `{payload['repo_count_expected'] if payload['repo_count_expected'] is not None else '-'}`",
        f"- Fleet score: `{_format_score(summary.get('fleet_score'))}`",
        f"- Cells: `{summary['cell_count']}`",
        "",
        "## Worst Metrics",
        "",
        "| metric | badness | avg_value | partial | n_a |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary["worst_metrics"]:
        lines.append(
            f"| `{_markdown_code(row['metric'])}` | {_format_score(row['badness'])} | {_format_score(row['avg_value'])} | "
            f"{row['partial_count']} | {row['n_a_count']} |"
        )
    lines.extend(["", "## Worst Dimensions", "", "| dimension | avg_cell_score | cells | flags |", "|---|---:|---:|---:|"])
    for row in summary["worst_dimensions"]:
        lines.append(
            f"| `{_markdown_code(row['dimension'])}` | {_format_score(row['avg_cell_score'])} | {row['cell_count']} | {row['flag_count']} |"
        )
    lines.extend(["", "## Lowest Repo Coverage", "", "| repo | avg_cell_score | cells | flags |", "|---|---:|---:|---:|"])
    for row in summary["repos_with_lowest_coverage"]:
        lines.append(f"| `{_markdown_code(row['repo'])}` | {_format_score(row['avg_cell_score'])} | {row['cell_count']} | {row['flag_count']} |")
    lines.extend(
        [
            "",
            "## Coverage Gaps",
            "",
            "| repo | owner | language | predicate | state | reason | files | details |",
            "|---|---|---|---|---|---|---:|---|",
        ]
    )
    for row in payload["coverage_gaps"]:
        lines.append(
            f"| `{_markdown_code(row['repo'])}` | `{_markdown_code(row['repo_owner'] or '-')}` | "
            f"`{_markdown_code(row['language'] or '-')}` | "
            f"`{_markdown_code(row['predicate'])}` | `{_markdown_code(row['state'])}` | "
            f"`{_markdown_code(row['reason'] or '-')}` | {row['file_count']} | "
            f"`{_markdown_code(_coverage_gap_details(row))}` |"
        )
    package_summary = payload["package_classification_summary"]
    lines.extend(["", "## Package Classification Summary", "", "### Buckets", "", "| bucket | count |", "|---|---:|"])
    for bucket, count in package_summary["bucket_counts"].items():
        lines.append(f"| `{_markdown_code(bucket)}` | {count} |")
    lines.extend(["", "### Actionable Reasons", "", "| actionable_reason | count |", "|---|---:|"])
    for reason, count in package_summary["actionable_reason_counts"].items():
        lines.append(f"| `{_markdown_code(reason)}` | {count} |")
    lines.extend(["", "### Non-Actionable Buckets", "", "| non_actionable_bucket | count |", "|---|---:|"])
    for bucket, count in package_summary["non_actionable_bucket_counts"].items():
        lines.append(f"| `{_markdown_code(bucket)}` | {count} |")
    lines.extend(["", "## Cells", "", "| repo | dimension | cell_score | flags |", "|---|---|---:|---:|"])
    for cell in payload["cells"]:
        lines.append(
            f"| `{_markdown_code(cell['repo'])}` | `{_markdown_code(cell['dimension'] or '-')}` | {_format_score(cell['cell_score'])} | "
            f"{len(cell['contract_flags'])} |"
        )
    return "\n".join(lines) + "\n"


def _read_manifest(snapshot: Path) -> JsonObject:
    path = snapshot / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Snapshot manifest is missing or not a file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _read_metrics(snapshot: Path) -> tuple[JsonObject, ...]:
    path = snapshot / METRICS_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Metrics file is missing or not a file: {path}; run coverage_metrics first")
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"{path}: metrics file must contain at least one row")
    metrics: list[JsonObject] = []
    seen: set[tuple[str, str | None]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
        _validate_metric_row(path, index, row)
        key = (str(row["repo"]), row["dimension"] if isinstance(row["dimension"], str) else None)
        if key in seen:
            raise ValueError(f"{path}: duplicate cell key {key!r}")
        seen.add(key)
        metrics.append(row)
    return tuple(metrics)


def _read_coverage(snapshot: Path) -> tuple[JsonObject, ...]:
    rows = [*list(_read_coverage_file(snapshot / "coverage.jsonl"))]
    rows.extend(_read_coverage_file(snapshot / "cross_repo_package_coverage.jsonl"))
    return tuple(rows)


def _read_coverage_file(path: Path) -> tuple[JsonObject, ...]:
    if not path.exists():
        return ()
    if not path.is_file():
        raise ValueError(f"Coverage file is not a regular file: {path}")
    rows = read_jsonl(path)
    coverage: list[JsonObject] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
        coverage.append(row)
    return tuple(coverage)


def _read_package_classifications(snapshot: Path) -> tuple[JsonObject, ...]:
    relink_path = snapshot / "cross_repo_package_classifications.jsonl"
    path = relink_path if relink_path.exists() else snapshot / "package_classifications.jsonl"
    if not path.exists():
        return ()
    if not path.is_file():
        raise ValueError(f"Package classification file is not a regular file: {path}")
    rows = read_jsonl(path)
    result: list[JsonObject] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
        result.append(row)
    return tuple(result)


def _validate_metric_row(path: Path, index: int, row: JsonObject) -> None:
    label = f"{path}: row {index + 1}"
    if not isinstance(row.get("repo"), str) or not row.get("repo"):
        raise ValueError(f"{label} repo must be a non-empty string")
    if not isinstance(row.get("built_at"), str) or not row.get("built_at"):
        raise ValueError(f"{label} built_at must be a non-empty string")
    if "dimension" not in row:
        raise ValueError(f"{label} missing required field: dimension")
    dimension = row.get("dimension")
    if dimension is not None and (not isinstance(dimension, str) or not dimension):
        raise ValueError(f"{label} dimension must be a non-empty string or null")
    if row.get("cell_score") is not None:
        _validate_ratio(row.get("cell_score"), f"{label} cell_score")
    metric_values = row.get("metric_values")
    if not isinstance(metric_values, dict) or not metric_values:
        raise ValueError(f"{label} metric_values must be a non-empty object")
    for metric_name, metric_value in metric_values.items():
        if not isinstance(metric_name, str) or not metric_name:
            raise ValueError(f"{label} metric name must be a non-empty string")
        if not isinstance(metric_value, dict):
            raise ValueError(f"{label} metric {metric_name} must be an object")
        state = metric_value.get("state")
        if state not in {"usable", "partial", "n_a"}:
            raise ValueError(f"{label} metric {metric_name} has unsupported state")
        value = metric_value.get("value")
        if state == "n_a":
            if value is not None:
                raise ValueError(f"{label} metric {metric_name} value must be null when state is n_a")
        else:
            _validate_ratio(value, f"{label} metric {metric_name} value")
        reason = metric_value.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"{label} metric {metric_name} reason must be a string or null")
        if state == "usable" and reason is not None:
            raise ValueError(f"{label} metric {metric_name} reason must be null when state is usable")
        if state in {"partial", "n_a"} and not reason:
            raise ValueError(f"{label} metric {metric_name} reason is required when state is {state}")
    flags = row.get("contract_flags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
        raise ValueError(f"{label} contract_flags must be a list of strings")
    commit_sha_set = row.get("commit_sha_set")
    if (
        not isinstance(commit_sha_set, list)
        or not commit_sha_set
        or any(not isinstance(commit, str) or not commit for commit in commit_sha_set)
    ):
        raise ValueError(f"{label} commit_sha_set must be a non-empty list of strings")


def _validate_ratio(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    if value < 0 or value > 1:
        raise ValueError(f"{label} must be between 0 and 1")


def _cell_payload(row: JsonObject) -> JsonObject:
    return {
        "repo": row["repo"],
        "dimension": row["dimension"],
        "cell_score": row.get("cell_score"),
        "metrics": row["metric_values"],
        "contract_flags": row["contract_flags"],
        "commit_sha_set": row["commit_sha_set"],
    }


def _summary(cells: tuple[JsonObject, ...], coverage_gaps: list[JsonObject]) -> JsonObject:
    return {
        "fleet_score": _average(_numeric_values(cell.get("cell_score") for cell in cells)),
        "cell_count": len(cells),
        "scored_cell_count": len(_numeric_values(cell.get("cell_score") for cell in cells)),
        "flag_count": sum(len(cell["contract_flags"]) for cell in cells),
        "coverage_gap_count": len(coverage_gaps),
        "worst_metrics": _worst_metrics(cells),
        "worst_dimensions": _worst_groups(cells, "dimension"),
        "repos_with_lowest_coverage": _worst_groups(cells, "repo"),
    }


def _package_classification_summary(rows: tuple[JsonObject, ...]) -> JsonObject:
    bucket_counts: dict[str, int] = {}
    actionable_reason_counts: dict[str, int] = {}
    for row in rows:
        bucket = row.get("bucket")
        if isinstance(bucket, str) and bucket:
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        reason = _classification_actionable_reason(row)
        if reason is not None:
            actionable_reason_counts[reason] = actionable_reason_counts.get(reason, 0) + 1
    non_actionable: dict[str, int] = {}
    for row in rows:
        bucket = row.get("bucket")
        if bucket not in {"builtin_or_stdlib", "consumer_manifest_external"}:
            continue
        if _classification_actionable_reason(row) is not None:
            continue
        non_actionable[str(bucket)] = non_actionable.get(str(bucket), 0) + 1
    return {
        "total": len(rows),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "non_actionable_bucket_counts": dict(sorted(non_actionable.items())),
        "actionable_reason_counts": dict(sorted(actionable_reason_counts.items())),
    }


def _classification_actionable_reason(row: JsonObject) -> str | None:
    bucket = row.get("bucket")
    reason = row.get("reason")
    if bucket == "candidate_internal_ambiguous":
        return "cross_repo_dependency_ambiguous_provider"
    if bucket == "unknown":
        return "cross_repo_dependency_unknown_category"
    if bucket == "consumer_manifest_external" and isinstance(reason, str) and reason.startswith(
        "path, workspace, or git dependency"
    ):
        return "cross_repo_dependency_no_provider"
    return None


def _coverage_gaps(manifest: JsonObject, coverage: tuple[JsonObject, ...]) -> list[JsonObject]:
    gaps = [_coverage_gap_payload(row) for row in coverage if _is_gap_coverage(row)]
    gaps.extend(_manifest_unsupported_language_gaps(manifest, gaps))
    return sorted(
        gaps,
        key=lambda row: (
            str(row["repo"]),
            str(row["language"] or ""),
            str(row["predicate"]),
            str(row["reason"] or ""),
        ),
    )


def _is_gap_coverage(row: JsonObject) -> bool:
    return row.get("state") in {"uninstrumented", "partially_instrumented", "stale"}


def _coverage_gap_payload(row: JsonObject) -> JsonObject:
    scope_ref = row.get("scope_ref")
    if not isinstance(scope_ref, dict):
        scope_ref = {}
    file_count = scope_ref.get("file_count")
    return {
        "repo": scope_ref.get("repo") if isinstance(scope_ref.get("repo"), str) else "-",
        "repo_owner": scope_ref.get("repo_owner") if isinstance(scope_ref.get("repo_owner"), str) else None,
        "language": scope_ref.get("language") if isinstance(scope_ref.get("language"), str) else None,
        "predicate": row.get("predicate") if isinstance(row.get("predicate"), str) else "-",
        "state": row.get("state") if isinstance(row.get("state"), str) else "-",
        "reason": scope_ref.get("reason") if isinstance(scope_ref.get("reason"), str) else None,
        "file_count": file_count if isinstance(file_count, int) and not isinstance(file_count, bool) and file_count >= 0 else 0,
        "sample_paths": scope_ref.get("sample_paths") if _is_string_list(scope_ref.get("sample_paths")) else [],
        "scope_ref": dict(scope_ref),
        "source_system": row.get("source_system") if isinstance(row.get("source_system"), str) else None,
    }


def _manifest_unsupported_language_gaps(manifest: JsonObject, existing_gaps: list[JsonObject]) -> list[JsonObject]:
    if isinstance(manifest.get("repos"), list):
        return []
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        return []
    unsupported = counts.get("unsupported_files_by_language")
    if not isinstance(unsupported, dict):
        return []
    repo_name = _manifest_repo_label(manifest)
    if repo_name is None:
        return []
    repo_owner = manifest.get("owner") if isinstance(manifest.get("owner"), str) and manifest.get("owner") else None
    seen = {
        (str(row["repo"]), row["language"], row["reason"])
        for row in existing_gaps
        if row.get("reason") == "unsupported_language"
    }
    gaps: list[JsonObject] = []
    for language, count in sorted(unsupported.items()):
        if (
            not isinstance(language, str)
            or not language
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            continue
        key = (repo_name, language, "unsupported_language")
        if key in seen:
            continue
        gaps.append(
            {
                "repo": repo_name,
                "repo_owner": repo_owner,
                "language": language,
                "predicate": "LANGUAGE_SUPPORT",
                "state": "uninstrumented",
                "reason": "unsupported_language",
                "file_count": count,
                "sample_paths": [],
                "scope_ref": {
                    "repo": repo_name,
                    "repo_owner": repo_owner,
                    "language": language,
                    "path_prefix": ".",
                    "reason": "unsupported_language",
                    "file_count": count,
                    "sample_paths": [],
                },
                "source_system": "manifest",
            }
        )
    return gaps


def _manifest_repo_label(manifest: JsonObject) -> str | None:
    repo_name = manifest.get("repo_name")
    if isinstance(repo_name, str) and repo_name:
        return repo_name
    return None


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _coverage_gap_details(row: JsonObject) -> str:
    scope_ref = row.get("scope_ref")
    if not isinstance(scope_ref, dict):
        return "-"
    skipped = {"repo", "repo_owner", "language", "reason", "file_count", "sample_paths"}
    parts = [
        f"{key}={_scope_value(value)}"
        for key, value in sorted(scope_ref.items())
        if key not in skipped and _scope_value(value)
    ]
    sample_paths = row.get("sample_paths")
    if _is_string_list(sample_paths) and sample_paths:
        parts.append("samples=" + ",".join(sample_paths[:3]))
    return "; ".join(parts) if parts else "-"


def _scope_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _worst_metrics(cells: tuple[JsonObject, ...]) -> list[JsonObject]:
    rows_by_metric: dict[str, list[JsonObject]] = {}
    for cell in cells:
        metrics = cell["metrics"]
        if not isinstance(metrics, dict):
            raise ValueError("cell metrics must be an object")
        for metric_name, metric_value in metrics.items():
            if not isinstance(metric_name, str) or not metric_name:
                raise ValueError("metric name must be a non-empty string")
            if not isinstance(metric_value, dict):
                raise ValueError(f"metric {metric_name} must be an object")
            rows_by_metric.setdefault(metric_name, []).append(metric_value)
    rows: list[JsonObject] = []
    for metric_name, metric_rows in rows_by_metric.items():
        values = _numeric_values(row.get("value") for row in metric_rows)
        avg_value = _average(values)
        partial_count = sum(1 for row in metric_rows if row.get("state") == "partial")
        n_a_count = sum(1 for row in metric_rows if row.get("state") == "n_a")
        badness = _metric_badness(metric_name, avg_value, partial_count, n_a_count, len(metric_rows))
        rows.append(
            {
                "metric": metric_name,
                "badness": badness,
                "avg_value": avg_value,
                "partial_count": partial_count,
                "n_a_count": n_a_count,
            }
        )
    return sorted(rows, key=lambda row: (-float(row["badness"]), str(row["metric"])))


def _metric_badness(metric_name: str, avg_value: float | None, partial_count: int, n_a_count: int, total: int) -> float:
    state_penalty = (partial_count + n_a_count) / total if total else 0.0
    if avg_value is None:
        return min(1.0, state_penalty or 1.0)
    if metric_name in LOWER_IS_BETTER_METRICS:
        value_badness = avg_value
    else:
        value_badness = 1.0 - avg_value
    return min(1.0, max(0.0, (value_badness + state_penalty) / 2 if state_penalty else value_badness))


def _worst_groups(cells: tuple[JsonObject, ...], key: str) -> list[JsonObject]:
    """Return groups in worst-first order: lowest score, then highest flag count."""
    grouped: dict[str, list[JsonObject]] = {}
    for cell in cells:
        value = cell.get(key)
        group = value if isinstance(value, str) and value else "-"
        grouped.setdefault(group, []).append(cell)
    rows: list[JsonObject] = []
    for group, group_cells in grouped.items():
        rows.append(
            {
                key: group,
                "avg_cell_score": _average(_numeric_values(cell.get("cell_score") for cell in group_cells)),
                "cell_count": len(group_cells),
                "flag_count": sum(len(cell["contract_flags"]) for cell in group_cells),
            }
        )
    return sorted(rows, key=lambda row: (_score_for_sort(row["avg_cell_score"]), -int(row["flag_count"]), str(row[key])))


def _numeric_values(values: Any) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result.append(float(value))
    return result


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _score_for_sort(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 2.0
    return float(value)


def _tenant(manifest: JsonObject) -> str:
    tenant_id = manifest.get("tenant_id")
    return tenant_id if isinstance(tenant_id, str) and tenant_id else "default"


def _repo_count(manifest: JsonObject) -> int | None:
    repos = manifest.get("repos")
    if isinstance(repos, list) and repos:
        return len(repos)
    repo_count = manifest.get("repo_count")
    if isinstance(repo_count, int) and not isinstance(repo_count, bool) and repo_count > 0:
        return repo_count
    if isinstance(manifest.get("repo_name"), str) and manifest.get("repo_name"):
        return 1
    return None


def _metrics_built_at_set(metrics: tuple[JsonObject, ...]) -> list[str]:
    return sorted(
        {
            value
            for row in metrics
            for value in (row.get("built_at"),)
            if isinstance(value, str) and value
        }
    )


def _format_score(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{float(value):.3f}"


def _markdown_code(value: object) -> str:
    text = " ".join(str(value).split())
    return text.replace("|", "\\|").replace("`", "'")


def _atomic_write_text(path: Path, content: str) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
