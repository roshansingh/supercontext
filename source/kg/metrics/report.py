from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from source.kg.core.models import JsonObject, utc_now_iso
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
    payload = build_coverage_report_payload(
        snapshot,
        manifest,
        metrics,
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
    return {
        "schema_version": 1,
        "run_id": run_id or snapshot_dir.name,
        "tenant": tenant or _tenant(manifest),
        "snapshot_dir": str(snapshot_dir),
        "snapshot_built_at": manifest.get("built_at") if isinstance(manifest.get("built_at"), str) else None,
        "generated_at": utc_now_iso(),
        "metric_config": metric_config,
        "repo_count_expected": expected_repos,
        "repo_count_indexed": _repo_count(manifest),
        "summary": _summary(cells),
        "cells": list(cells),
    }


def render_coverage_report_markdown(payload: JsonObject) -> str:
    summary = payload["summary"]
    lines = [
        f"# Coverage Run: {payload['run_id']}",
        "",
        f"- Tenant: `{payload['tenant']}`",
        f"- Snapshot: `{payload['snapshot_dir']}`",
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
            f"| `{row['metric']}` | {_format_score(row['badness'])} | {_format_score(row['avg_value'])} | "
            f"{row['partial_count']} | {row['n_a_count']} |"
        )
    lines.extend(["", "## Worst Dimensions", "", "| dimension | avg_cell_score | cells | flags |", "|---|---:|---:|---:|"])
    for row in summary["worst_dimensions"]:
        lines.append(
            f"| `{row['dimension']}` | {_format_score(row['avg_cell_score'])} | {row['cell_count']} | {row['flag_count']} |"
        )
    lines.extend(["", "## Lowest Repo Coverage", "", "| repo | avg_cell_score | cells | flags |", "|---|---:|---:|---:|"])
    for row in summary["repos_with_lowest_coverage"]:
        lines.append(f"| `{row['repo']}` | {_format_score(row['avg_cell_score'])} | {row['cell_count']} | {row['flag_count']} |")
    lines.extend(["", "## Cells", "", "| repo | dimension | cell_score | flags |", "|---|---|---:|---:|"])
    for cell in payload["cells"]:
        lines.append(
            f"| `{cell['repo']}` | `{cell['dimension'] or '-'}` | {_format_score(cell['cell_score'])} | "
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


def _validate_metric_row(path: Path, index: int, row: JsonObject) -> None:
    label = f"{path}: row {index + 1}"
    if not isinstance(row.get("repo"), str) or not row.get("repo"):
        raise ValueError(f"{label} repo must be a non-empty string")
    if row.get("dimension") is not None and not isinstance(row.get("dimension"), str):
        raise ValueError(f"{label} dimension must be a string or null")
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
    if not isinstance(commit_sha_set, list) or not commit_sha_set or any(not isinstance(commit, str) for commit in commit_sha_set):
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


def _summary(cells: tuple[JsonObject, ...]) -> JsonObject:
    return {
        "fleet_score": _average(_numeric_values(cell.get("cell_score") for cell in cells)),
        "cell_count": len(cells),
        "scored_cell_count": len(_numeric_values(cell.get("cell_score") for cell in cells)),
        "flag_count": sum(len(cell["contract_flags"]) for cell in cells),
        "worst_metrics": _worst_metrics(cells),
        "worst_dimensions": _worst_groups(cells, "dimension"),
        "repos_with_lowest_coverage": _worst_groups(cells, "repo"),
    }


def _worst_metrics(cells: tuple[JsonObject, ...]) -> list[JsonObject]:
    rows_by_metric: dict[str, list[JsonObject]] = {}
    for cell in cells:
        metrics = cell["metrics"]
        assert isinstance(metrics, dict)
        for metric_name, metric_value in metrics.items():
            assert isinstance(metric_name, str)
            assert isinstance(metric_value, dict)
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


def _format_score(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{float(value):.3f}"


def _atomic_write_text(path: Path, content: str) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
