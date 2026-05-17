from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.core.models import JsonObject, utc_now_iso
from source.kg.core.store import read_jsonl
from source.kg.metrics import compute_all
from source.kg.metrics.types import METRIC_STATES, CellMetrics

METRICS_FILENAME = "metrics.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute BetterContext KG coverage metrics for a JSONL snapshot."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", help="Path to a KG snapshot directory.")
    mode.add_argument(
        "--compare",
        nargs=2,
        metavar=("BEFORE_SNAPSHOT", "AFTER_SNAPSHOT"),
        help="Compare persisted metrics.jsonl files from two snapshot directories.",
    )
    parser.add_argument("--fleet-dir", help="Optional fleet artifact directory for linker freshness checks.")
    parser.add_argument("--expected-repos", type=int, help="Expected repo denominator for M_inventory.")
    parser.add_argument("--config", help="Optional metrics config YAML path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON records instead of a compact table.")
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write or overwrite <snapshot>/metrics.jsonl when computing snapshot metrics.",
    )
    args = parser.parse_args(argv)

    if args.compare:
        ignored_compare_args = [
            flag
            for flag, value, default in (
                ("--fleet-dir", args.fleet_dir, None),
                ("--expected-repos", args.expected_repos, None),
                ("--config", args.config, None),
                ("--no-persist", args.no_persist, False),
            )
            if value != default
        ]
        if ignored_compare_args:
            parser.error(f"{', '.join(ignored_compare_args)} can only be used with --snapshot")
        deltas = compare_metrics(Path(args.compare[0]), Path(args.compare[1]))
        if args.json:
            for delta in deltas:
                print(json.dumps(delta, sort_keys=True))
            return 0
        _print_delta_table(deltas)
        return 0

    snapshot = Path(args.snapshot)
    cells = compute_all(
        snapshot,
        fleet_dir=Path(args.fleet_dir) if args.fleet_dir else None,
        expected_repos=args.expected_repos,
        config_path=Path(args.config) if args.config else None,
    )
    records = _metric_records(cells)
    if not args.no_persist:
        _write_metrics_records(snapshot, records)
    if args.json:
        for record in records:
            print(json.dumps(record, sort_keys=True))
        return 0

    _print_table(cells)
    return 0


def persist_metrics(snapshot_dir: Path, cells: tuple[CellMetrics, ...]) -> tuple[JsonObject, ...]:
    records = _metric_records(cells)
    _write_metrics_records(snapshot_dir, records)
    return records


def _metric_records(cells: tuple[CellMetrics, ...]) -> tuple[JsonObject, ...]:
    built_at = utc_now_iso()
    return tuple({**cell.to_record(), "built_at": built_at} for cell in cells)


def _write_metrics_records(snapshot_dir: Path, records: tuple[JsonObject, ...]) -> None:
    path = snapshot_dir.expanduser().resolve() / METRICS_FILENAME
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def compare_metrics(before_snapshot: Path, after_snapshot: Path) -> tuple[JsonObject, ...]:
    before = _read_metrics_file(before_snapshot)
    after = _read_metrics_file(after_snapshot)
    before_by_key = _metrics_by_key(before, before_snapshot)
    after_by_key = _metrics_by_key(after, after_snapshot)

    deltas: list[JsonObject] = []
    for key in sorted(before_by_key.keys() | after_by_key.keys()):
        before_value = before_by_key.get(key)
        after_value = after_by_key.get(key)
        repo, dimension, metric = key
        before_metric = _metric_payload(before_value, metric) if before_value is not None else None
        after_metric = _metric_payload(after_value, metric) if after_value is not None else None
        deltas.append(
            {
                "repo": repo,
                "dimension": None if dimension == "" else dimension,
                "metric": metric,
                "before": before_metric,
                "after": after_metric,
                "value_delta": _value_delta(before_metric, after_metric),
                "state_changed": _state(before_metric) != _state(after_metric),
            }
        )
    return tuple(deltas)


def _print_table(cells: tuple[CellMetrics, ...]) -> None:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for cell in cells:
        for metric_name, metric_value in sorted(cell.metric_values.items()):
            rows.append(
                (
                    cell.repo,
                    cell.dimension or "-",
                    metric_name,
                    "-" if metric_value.value is None else f"{metric_value.value:.3f}",
                    metric_value.state,
                    metric_value.reason or "",
                )
            )
    headers = ("repo", "dimension", "metric", "value", "state", "reason")
    widths = [
        max(len(str(row[index])) for row in (headers, *rows))
        for index in range(len(headers))
    ]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _print_delta_table(deltas: tuple[JsonObject, ...]) -> None:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for delta in deltas:
        before = delta["before"]
        after = delta["after"]
        rows.append(
            (
                str(delta["repo"]),
                str(delta["dimension"] or "-"),
                str(delta["metric"]),
                _format_metric_cell(before),
                _format_metric_cell(after),
                "-" if delta["value_delta"] is None else f"{delta['value_delta']:.3f}",
            )
        )
    headers = ("repo", "dimension", "metric", "before", "after", "delta")
    widths = [
        max(len(str(row[index])) for row in (headers, *rows))
        for index in range(len(headers))
    ]
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def _read_metrics_file(snapshot_dir: Path) -> tuple[JsonObject, ...]:
    path = snapshot_dir.expanduser().resolve() / METRICS_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"Metrics file does not exist: {path}")
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"{path}: metrics file must contain at least one row")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index + 1} must be a JSON object")
    return tuple(rows)


def _metrics_by_key(rows: tuple[JsonObject, ...], snapshot_dir: Path) -> dict[tuple[str, str, str], JsonObject]:
    result: dict[tuple[str, str, str], JsonObject] = {}
    for index, row in enumerate(rows):
        repo = row.get("repo")
        dimension = row.get("dimension")
        metric_values = row.get("metric_values")
        if not isinstance(repo, str) or not repo:
            raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: row {index + 1} repo must be a non-empty string")
        if dimension is not None and (not isinstance(dimension, str) or not dimension):
            raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: row {index + 1} dimension must be null or a non-empty string")
        if not isinstance(metric_values, dict) or not metric_values:
            raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: row {index + 1} metric_values must be a non-empty object")
        for metric_name, metric_value in metric_values.items():
            if not isinstance(metric_name, str) or not metric_name:
                raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: row {index + 1} metric name must be a non-empty string")
            if not isinstance(metric_value, dict):
                raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: row {index + 1} metric {metric_name} must be an object")
            _validate_metric_payload(snapshot_dir, index, metric_name, metric_value)
            key = (repo, dimension or "", metric_name)
            if key in result:
                raise ValueError(f"{snapshot_dir / METRICS_FILENAME}: duplicate metric key {key!r}")
            result[key] = row
    return result


def _metric_payload(row: JsonObject, metric: str) -> JsonObject:
    metric_values = row.get("metric_values")
    if not isinstance(metric_values, dict):
        raise ValueError("metric_values must be an object")
    value = metric_values.get(metric)
    if not isinstance(value, dict):
        raise ValueError(f"metric {metric} must be an object")
    return value


def _validate_metric_payload(snapshot_dir: Path, row_index: int, metric_name: str, value: JsonObject) -> None:
    path = snapshot_dir / METRICS_FILENAME
    state = value.get("state")
    metric_value = value.get("value")
    reason = value.get("reason")
    if state not in METRIC_STATES:
        raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.state is not supported")
    if state == "n_a":
        if metric_value is not None:
            raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.value must be null when state is n_a")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.reason is required when state is n_a")
        return
    if not isinstance(metric_value, (int, float)) or isinstance(metric_value, bool):
        raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.value must be numeric")
    if state == "usable" and reason is not None:
        raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.reason must be null when state is usable")
    if state == "partial" and (not isinstance(reason, str) or not reason):
        raise ValueError(f"{path}: row {row_index + 1} metric {metric_name}.reason is required when state is partial")


def _value_delta(before: JsonObject | None, after: JsonObject | None) -> float | None:
    before_value = before.get("value") if before is not None else None
    after_value = after.get("value") if after is not None else None
    if not isinstance(before_value, (int, float)) or isinstance(before_value, bool):
        return None
    if not isinstance(after_value, (int, float)) or isinstance(after_value, bool):
        return None
    return float(after_value) - float(before_value)


def _state(metric: JsonObject | None) -> str | None:
    return metric.get("state") if metric is not None else None


def _format_metric_cell(metric: JsonObject | None) -> str:
    if metric is None:
        return "missing"
    value = metric.get("value")
    state = metric.get("state")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value_text = f"{value:.3f}"
    else:
        value_text = "-"
    return f"{value_text}/{state}"


if __name__ == "__main__":
    raise SystemExit(main())
