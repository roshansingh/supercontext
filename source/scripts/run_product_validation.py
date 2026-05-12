from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.product.validation_report import (
    DEFAULT_NEXT_FEATURE_RECOMMENDATION,
    ValidationConfig,
    default_generated_at,
    render_product_query_matrix_markdown,
    render_validation_markdown,
    run_canonical_validation,
)


DEFAULT_MERCURY_SNAPSHOT = "data/kg_runs/mercury_ml_eval_2026_05_11"
DEFAULT_TRUE_LOOP_SNAPSHOT = "data/kg_runs/true_loop_eval_2026_05_11"
DEFAULT_PRIVATE_SNAPSHOT = "data/kg_runs/private_goldset_eval_2026_05_11"
DEFAULT_GOLDSET_PACKETS = "data/kg_runs/private_goldset_eval_2026_05_11/goldset_packets_eval_2026_05_11.json"
DEFAULT_GOLDSET_ANSWERS = "data/kg_runs/private_goldset_eval_2026_05_11/goldset_answers_eval_2026_05_11.json"
DEFAULT_GOLDSET_JUDGEMENT = "data/kg_runs/private_goldset_eval_2026_05_11/goldset_judgement_eval_2026_05_11.json"
DEFAULT_MD_OUT = "docs/evaluation/CANONICAL-VALIDATION-REPORT.md"
DEFAULT_EVALUATION_DIR = "docs/evaluation"
DEFAULT_PRIVATE_SMOKE_FIXTURES = "examples/private-goldset/smoke_fixtures.json"
DEFAULT_PRODUCT_QUERY_SET = "docs/evaluation/PRODUCT-QUERY-SET.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the canonical product-validation report.")
    parser.add_argument("--mercury-snapshot", default=DEFAULT_MERCURY_SNAPSHOT)
    parser.add_argument("--true-loop-snapshot", default=DEFAULT_TRUE_LOOP_SNAPSHOT)
    parser.add_argument("--private-snapshot", default=DEFAULT_PRIVATE_SNAPSHOT)
    parser.add_argument("--goldset-packets", default=DEFAULT_GOLDSET_PACKETS)
    parser.add_argument("--goldset-answers", default=DEFAULT_GOLDSET_ANSWERS)
    parser.add_argument("--goldset-judgement", default=DEFAULT_GOLDSET_JUDGEMENT)
    parser.add_argument("--product-query-set", default=DEFAULT_PRODUCT_QUERY_SET)
    parser.add_argument("--evaluation-dir", default=DEFAULT_EVALUATION_DIR)
    parser.add_argument("--private-smoke-fixtures", default=DEFAULT_PRIVATE_SMOKE_FIXTURES)
    parser.add_argument(
        "--next-feature-recommendation",
        help="Operator-authored recommendation to render in the Product Readout section.",
    )
    parser.add_argument("--generated-at", default=default_generated_at())
    parser.add_argument("--json-out", help="Optional path to write the machine-readable report JSON.")
    parser.add_argument("--md-out", default=DEFAULT_MD_OUT, help="Markdown report output path.")
    parser.add_argument("--query-matrix-md-out", help="Optional path to write the product-query-set matrix Markdown.")
    parser.add_argument(
        "--no-md",
        action="store_true",
        help="Skip the main validation Markdown report; print JSON only when no file outputs are requested.",
    )
    parser.add_argument(
        "--no-strict-smoke-checks",
        action="store_true",
        help="Record unexpected smoke-check exceptions as failed rows instead of failing the command.",
    )
    args = parser.parse_args()

    report = run_canonical_validation(
        ValidationConfig(
            mercury_snapshot=Path(args.mercury_snapshot),
            true_loop_snapshot=Path(args.true_loop_snapshot),
            private_snapshot=Path(args.private_snapshot),
            goldset_packets=Path(args.goldset_packets),
            goldset_answers=Path(args.goldset_answers),
            goldset_judgement=Path(args.goldset_judgement),
            generated_at=args.generated_at,
            product_query_set=Path(args.product_query_set) if args.product_query_set else None,
            evaluation_dir=Path(args.evaluation_dir),
            strict_smoke_checks=not args.no_strict_smoke_checks,
            private_smoke_fixtures=Path(args.private_smoke_fixtures),
            next_feature_recommendation=(
                args.next_feature_recommendation or DEFAULT_NEXT_FEATURE_RECOMMENDATION
            ),
        )
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        _write_text(Path(args.json_out), payload + "\n")
    if not args.no_md:
        _write_text(Path(args.md_out), render_validation_markdown(report))
    if args.query_matrix_md_out:
        _write_text(Path(args.query_matrix_md_out), render_product_query_matrix_markdown(report))
    if args.no_md and not args.json_out and not args.query_matrix_md_out:
        print(payload)


def _write_text(path: Path, value: str) -> None:
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
