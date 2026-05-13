from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

from source.kg.core.models import JsonObject


BASELINE_VERSION = 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a distilled KG snapshot baseline.")
    parser.add_argument("snapshot", help="Directory containing KG JSONL files and manifest.json")
    parser.add_argument("--name", help="Optional stable baseline name. Defaults to the snapshot directory name.")
    parser.add_argument("--out", required=True, help="Output JSON baseline path")
    args = parser.parse_args()

    baseline = capture_snapshot_baseline(Path(args.snapshot), name=args.name)
    _warn_unknown_coverage_reasons(baseline)
    output_path = Path(args.out).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def capture_snapshot_baseline(snapshot: Path, name: str | None = None) -> JsonObject:
    snapshot_path = snapshot.expanduser().resolve()
    manifest = _load_json(snapshot_path / "manifest.json")
    _require_file(snapshot_path / "evidence.jsonl")
    if not isinstance(manifest, dict):
        raise ValueError(f"{snapshot_path / 'manifest.json'} must contain a JSON object")

    extractor_errors = manifest.get("extractor_errors", [])
    if not isinstance(extractor_errors, list):
        raise ValueError("manifest.json field 'extractor_errors' must be a list when present")

    return {
        "baseline_version": BASELINE_VERSION,
        "name": name or snapshot_path.name,
        "manifest_counts": _string_int_map(manifest.get("counts", {}), "manifest.counts"),
        "extractor_errors_count": len(extractor_errors),
        "entity_kind_counts": _counter_dict(
            _required_string(row, "kind", "entities.jsonl") for row in _read_jsonl(snapshot_path / "entities.jsonl")
        ),
        "fact_predicate_counts": _counter_dict(
            _required_string(row, "predicate", "facts.jsonl") for row in _read_jsonl(snapshot_path / "facts.jsonl")
        ),
        "coverage_reason_counts": _counter_dict(_coverage_reason(row) for row in _read_jsonl(snapshot_path / "coverage.jsonl")),
    }


def _load_json(path: Path) -> object:
    _require_file(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required snapshot file: {path}")


def _read_jsonl(path: Path) -> Iterable[JsonObject]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required snapshot file: {path}")
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            yield row


def _coverage_reason(row: JsonObject) -> str:
    scope_ref = row.get("scope_ref", {})
    if isinstance(scope_ref, dict):
        reason = scope_ref.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return "unknown"


def _warn_unknown_coverage_reasons(baseline: JsonObject) -> None:
    coverage_counts = baseline.get("coverage_reason_counts", {})
    if not isinstance(coverage_counts, dict):
        return
    unknown_count = coverage_counts.get("unknown")
    if isinstance(unknown_count, int) and unknown_count > 0:
        print(
            f"warning: captured {unknown_count} coverage rows without scope_ref.reason as 'unknown'",
            file=sys.stderr,
        )


def _required_string(row: JsonObject, field: str, label: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} field {field!r} must be a non-empty string")
    return value


def _counter_dict(values: Iterable[object]) -> JsonObject:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _string_int_map(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    result: JsonObject = {}
    for key, count in value.items():
        if not _is_int_count(count):
            raise ValueError(f"{label}.{key} must be an integer")
        result[str(key)] = count
    return dict(sorted(result.items()))


def _is_int_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


if __name__ == "__main__":
    main()
