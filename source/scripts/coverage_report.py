from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.metrics.report import write_coverage_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a stable JSON and Markdown coverage run report from metrics.jsonl.")
    parser.add_argument("--snapshot", required=True, help="Path to a KG snapshot directory containing metrics.jsonl.")
    parser.add_argument("--out", required=True, help="Output directory for coverage-run.json and coverage-run.md.")
    parser.add_argument("--run-id", help="Stable identifier for this coverage run. Defaults to the snapshot directory name.")
    parser.add_argument("--tenant", help="Tenant or organization label to record in the report.")
    parser.add_argument("--expected-repos", type=_positive_int, help="Expected repo denominator to record in the report.")
    parser.add_argument("--metric-config", help="Metric config path or identifier to record in the report.")
    parser.add_argument("--json", action="store_true", help="Print the generated coverage-run.json payload to stdout.")
    args = parser.parse_args(argv)

    report = write_coverage_report(
        Path(args.snapshot),
        Path(args.out),
        run_id=args.run_id,
        expected_repos=args.expected_repos,
        tenant=args.tenant,
        metric_config=args.metric_config,
    )
    if args.json:
        print(json.dumps(report.payload, sort_keys=True))
    else:
        print(f"Wrote {report.json_path}")
        print(f"Wrote {report.markdown_path}")
    return 0


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
