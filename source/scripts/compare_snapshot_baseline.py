from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import JsonObject
from source.scripts.capture_snapshot_baseline import (
    BASELINE_VERSION,
    NORMALIZED_COVERAGE_REASONS,
    capture_snapshot_baseline,
)


COMPARED_SECTIONS = (
    "manifest_counts",
    "extractor_errors_count",
    "entity_kind_counts",
    "fact_predicate_counts",
    "coverage_reason_counts",
)


@dataclass(frozen=True)
class Difference:
    section: str
    key: str
    expected: int | None
    actual: int | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a KG snapshot against a distilled baseline.")
    parser.add_argument("snapshot", help="Directory containing KG JSONL files and manifest.json")
    parser.add_argument("--baseline", required=True, help="Baseline JSON file captured by capture_snapshot_baseline")
    parser.add_argument(
        "--allow-additions",
        action="store_true",
        help=(
            "Allow added distribution keys and count increases, but still fail on removals, "
            "count decreases, or extractor error count changes."
        ),
    )
    args = parser.parse_args()

    baseline = load_baseline(Path(args.baseline))
    actual = capture_snapshot_baseline(Path(args.snapshot), name=str(baseline.get("name") or "actual"))
    differences = compare_snapshot_baseline(actual, baseline, allow_additions=args.allow_additions)
    print(render_differences(differences))
    raise SystemExit(1 if differences else 0)


def compare_snapshot_baseline(actual: JsonObject, expected: JsonObject, allow_additions: bool = False) -> list[Difference]:
    differences: list[Difference] = []
    for section in COMPARED_SECTIONS:
        actual_value = actual.get(section)
        expected_value = expected.get(section)
        if isinstance(expected_value, dict):
            if not isinstance(actual_value, dict):
                differences.append(Difference(section, "<section>", None, None))
                continue
            differences.extend(_compare_mapping(section, actual_value, expected_value, allow_additions))
        elif _is_int_count(expected_value):
            if not _is_int_count(actual_value):
                differences.append(Difference(section, "<value>", expected_value, None))
            elif _is_drift(actual_value, expected_value, _allow_additions_for_section(section, allow_additions)):
                differences.append(Difference(section, "<value>", expected_value, actual_value))
        else:
            raise ValueError(f"Unsupported baseline section {section!r}: {type(expected_value).__name__}")
    return differences


def render_differences(differences: list[Difference]) -> str:
    if not differences:
        return "Snapshot matches baseline."
    lines = [
        "Snapshot differs from baseline:",
        "",
        "| Section | Key | Expected | Actual |",
        "|---|---|---:|---:|",
    ]
    for diff in differences:
        lines.append(
            f"| {diff.section} | {diff.key} | {_display_count(diff.expected)} | {_display_count(diff.actual)} |"
        )
    return "\n".join(lines)


def _compare_mapping(
    section: str,
    actual: JsonObject,
    expected: JsonObject,
    allow_additions: bool,
) -> list[Difference]:
    differences = []
    for key in sorted(set(expected) | set(actual)):
        expected_count = _int_or_none(expected.get(key))
        actual_count = _int_or_none(actual.get(key))
        if expected_count is None:
            if not allow_additions:
                differences.append(Difference(section, str(key), None, actual_count))
            continue
        if actual_count is None:
            differences.append(Difference(section, str(key), expected_count, None))
            continue
        if _is_drift(actual_count, expected_count, allow_additions):
            differences.append(Difference(section, str(key), expected_count, actual_count))
    return differences


def _allow_additions_for_section(section: str, allow_additions: bool) -> bool:
    return allow_additions and section != "extractor_errors_count"


def _is_drift(actual: int, expected: int, allow_additions: bool) -> bool:
    if allow_additions:
        return actual < expected
    return actual != expected


def load_baseline(path: Path) -> JsonObject:
    baseline = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(baseline, dict):
        raise ValueError(f"{path} must contain a JSON object")
    _validate_baseline(baseline, str(path))
    _normalize_loaded_baseline(baseline)
    return baseline


def _normalize_loaded_baseline(baseline: JsonObject) -> None:
    coverage_counts = baseline.get("coverage_reason_counts")
    if not isinstance(coverage_counts, dict):
        return
    normalized: dict[str, int] = {}
    for reason, count in coverage_counts.items():
        if not isinstance(reason, str) or not _is_int_count(count):
            continue
        normalized_reason = NORMALIZED_COVERAGE_REASONS.get(reason, reason)
        normalized[normalized_reason] = normalized.get(normalized_reason, 0) + count
    baseline["coverage_reason_counts"] = normalized


def _validate_baseline(baseline: JsonObject, label: str) -> None:
    version = baseline.get("baseline_version")
    if version != BASELINE_VERSION:
        raise ValueError(f"{label} baseline_version must be {BASELINE_VERSION}")
    for section in COMPARED_SECTIONS:
        if section not in baseline:
            raise ValueError(f"{label} is missing required section {section!r}")
        value = baseline[section]
        if section == "extractor_errors_count":
            if not _is_int_count(value):
                raise ValueError(f"{label}.{section} must be an integer")
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{label}.{section} must be an object")
        for key, count in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label}.{section} keys must be strings")
            if not _is_int_count(count):
                raise ValueError(f"{label}.{section}.{key} must be an integer")


def _int_or_none(value: object) -> int | None:
    return value if _is_int_count(value) else None


def _is_int_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _display_count(value: int | None) -> str:
    return "missing" if value is None else str(value)


if __name__ == "__main__":
    main()
