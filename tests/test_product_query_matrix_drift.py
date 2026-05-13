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

        _assert_expected_summary_shape(self, expected)

    def test_expected_summary_shape_rejects_boolean_counts(self) -> None:
        expected = _load_expected_summary()
        expected["query_count"] = True
        with self.assertRaises(AssertionError):
            _assert_expected_summary_shape(self, expected)

        expected = _load_expected_summary()
        expected["status_summary"] = {"pass": False}
        with self.assertRaises(AssertionError):
            _assert_expected_summary_shape(self, expected)

    def test_expected_summary_shape_rejects_fractional_counts(self) -> None:
        expected = _load_expected_summary()
        expected["query_count"] = 110.5
        with self.assertRaises(AssertionError):
            _assert_expected_summary_shape(self, expected)

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


def _assert_expected_summary_shape(test_case: unittest.TestCase, expected: dict[str, object]) -> None:
    test_case.assertEqual(set(expected), set(_EXPECTED_SUMMARY_KEYS))
    for key in ("query_count", "tuple_count", "measured_query_count", "unmeasured_query_count"):
        test_case.assertTrue(_is_json_int(expected[key]), f"{key} must be a JSON integer, not bool")
    for key in ("measured_query_coverage_pct",):
        test_case.assertTrue(_is_json_number(expected[key]), f"{key} must be a JSON number, not bool")
    test_case.assertIsInstance(expected["harness_sources"], list)
    test_case.assertTrue(all(isinstance(value, str) for value in expected["harness_sources"]))
    test_case.assertIsInstance(expected["status_summary"], dict)
    test_case.assertIsInstance(expected["failure_owner_summary"], dict)
    test_case.assertTrue(all(_is_json_int(value) for value in expected["status_summary"].values()))
    test_case.assertTrue(all(_is_json_int(value) for value in expected["failure_owner_summary"].values()))


def _is_json_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_json_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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
