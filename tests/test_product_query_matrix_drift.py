from __future__ import annotations

import json
import unittest
from pathlib import Path

from source.kg.product.validation_report import ValidationConfig, run_canonical_validation
from source.scripts.run_product_validation import (
    DEFAULT_EVALUATION_DIR,
    DEFAULT_GOLDSET_ANSWERS,
    DEFAULT_GOLDSET_JUDGEMENT,
    DEFAULT_GOLDSET_PACKETS,
    DEFAULT_MERCURY_SNAPSHOT,
    DEFAULT_PRIVATE_SMOKE_FIXTURES,
    DEFAULT_PRIVATE_SNAPSHOT,
    DEFAULT_PRODUCT_QUERY_SET,
    DEFAULT_TRUE_LOOP_SNAPSHOT,
)


EXPECTED_PATH = Path("docs/evaluation/PRODUCT-QUERY-SET-RUN-EXPECTED.json")


class ProductQueryMatrixDriftTest(unittest.TestCase):
    def test_expected_summary_file_shape_is_valid_without_local_snapshots(self) -> None:
        expected = _load_expected_summary()

        self.assertEqual(set(expected), set(_EXPECTED_SUMMARY_KEYS))
        for key in (
            "query_count",
            "tuple_count",
            "measured_query_count",
            "unmeasured_query_count",
            "measured_query_coverage_pct",
        ):
            self.assertIsInstance(expected[key], int | float)
        self.assertIsInstance(expected["harness_sources"], list)
        self.assertTrue(all(isinstance(value, str) for value in expected["harness_sources"]))
        self.assertIsInstance(expected["status_summary"], dict)
        self.assertIsInstance(expected["failure_owner_summary"], dict)
        self.assertTrue(all(isinstance(value, int) for value in expected["status_summary"].values()))
        self.assertTrue(all(isinstance(value, int) for value in expected["failure_owner_summary"].values()))

    def test_available_product_query_matrix_matches_expected_summary(self) -> None:
        required_paths = [
            Path(DEFAULT_MERCURY_SNAPSHOT),
            Path(DEFAULT_TRUE_LOOP_SNAPSHOT),
            Path(DEFAULT_PRIVATE_SNAPSHOT),
            Path(DEFAULT_GOLDSET_PACKETS),
            Path(DEFAULT_GOLDSET_ANSWERS),
            Path(DEFAULT_GOLDSET_JUDGEMENT),
            Path(DEFAULT_PRIVATE_SMOKE_FIXTURES),
            Path(DEFAULT_PRODUCT_QUERY_SET),
            EXPECTED_PATH,
        ]
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            self.skipTest("Missing local validation artifacts; skipping product-query matrix drift: " + ", ".join(missing))

        expected = _load_expected_summary()
        report = run_canonical_validation(
            ValidationConfig(
                mercury_snapshot=Path(DEFAULT_MERCURY_SNAPSHOT),
                true_loop_snapshot=Path(DEFAULT_TRUE_LOOP_SNAPSHOT),
                private_snapshot=Path(DEFAULT_PRIVATE_SNAPSHOT),
                goldset_packets=Path(DEFAULT_GOLDSET_PACKETS),
                goldset_answers=Path(DEFAULT_GOLDSET_ANSWERS),
                goldset_judgement=Path(DEFAULT_GOLDSET_JUDGEMENT),
                generated_at="1970-01-01T00:00:00Z",
                product_query_set=Path(DEFAULT_PRODUCT_QUERY_SET),
                evaluation_dir=Path(DEFAULT_EVALUATION_DIR),
                private_smoke_fixtures=Path(DEFAULT_PRIVATE_SMOKE_FIXTURES),
            )
        )

        actual = _matrix_expected_summary(report["product_query_matrix"])
        self.assertEqual(actual, expected)


_EXPECTED_SUMMARY_KEYS = (
    "query_count",
    "tuple_count",
    "measured_query_count",
    "unmeasured_query_count",
    "measured_query_coverage_pct",
    "harness_sources",
    "status_summary",
    "failure_owner_summary",
)


def _load_expected_summary() -> dict[str, object]:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    if not isinstance(expected, dict):
        raise AssertionError(f"{EXPECTED_PATH} must contain a JSON object")
    return expected


def _matrix_expected_summary(matrix: dict[str, object]) -> dict[str, object]:
    return {
        "query_count": matrix["query_count"],
        "tuple_count": matrix["tuple_count"],
        "measured_query_count": matrix["measured_query_count"],
        "unmeasured_query_count": matrix["unmeasured_query_count"],
        "measured_query_coverage_pct": matrix["measured_query_coverage_pct"],
        "harness_sources": matrix["harness_sources"],
        "status_summary": matrix["status_summary"],
        "failure_owner_summary": matrix["failure_owner_summary"],
    }


if __name__ == "__main__":
    unittest.main()
