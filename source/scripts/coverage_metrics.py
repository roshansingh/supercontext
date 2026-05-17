from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.metrics import compute_all
from source.kg.metrics.types import CellMetrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute BetterContext KG coverage metrics for a JSONL snapshot.")
    parser.add_argument("--snapshot", required=True, help="Path to a KG snapshot directory.")
    parser.add_argument("--fleet-dir", help="Optional fleet artifact directory for linker freshness checks.")
    parser.add_argument("--expected-repos", type=int, help="Expected repo denominator for M_inventory.")
    parser.add_argument("--config", help="Optional metrics config YAML path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON records instead of a compact table.")
    args = parser.parse_args(argv)

    cells = compute_all(
        Path(args.snapshot),
        fleet_dir=Path(args.fleet_dir) if args.fleet_dir else None,
        expected_repos=args.expected_repos,
        config_path=Path(args.config) if args.config else None,
    )
    if args.json:
        for cell in cells:
            print(json.dumps(cell.to_record(), sort_keys=True))
        return 0

    _print_table(cells)
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
