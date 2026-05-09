from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.kg.product.answer_synthesis import _validate_answer
from source.kg.product.claude_tool_policy import resolve_claude_cli_path
from source.kg.product.goldset_judgement import _validate_judgement, load_goldset_scenarios
from source.kg.product.json_result import parse_json_object_result
from source.kg.product.validation import normalize_unique_strings, require_unique_strings
from source.scripts.run_goldset_answers import _load_or_build_packets
from source.scripts.run_goldset_judgement import _load_by_scenario


class GoldsetHarnessValidationTest(unittest.TestCase):
    def test_packets_in_accepts_top_level_list_and_normalizes_id(self) -> None:
        path = _write_json([{"scenario_id": " Q082\n", "evidence_items": [], "retrieval_steps": [], "unknowns": []}])

        packets = _load_or_build_packets("unused", ("Q082",), str(path))

        self.assertEqual(packets[0]["scenario_id"], "Q082")

    def test_packets_in_rejects_duplicate_requested_scenario(self) -> None:
        path = _write_json([{"scenario_id": "Q082"}, {"scenario_id": "Q082"}])

        with self.assertRaisesRegex(ValueError, "duplicates scenario_id"):
            _load_or_build_packets("unused", ("Q082",), str(path))

    def test_packets_in_rejects_malformed_list_fields(self) -> None:
        path = _write_json([{"scenario_id": "Q082", "evidence_items": "bad"}])

        with self.assertRaisesRegex(ValueError, "evidence_items must be a list"):
            _load_or_build_packets("unused", ("Q082",), str(path))

    def test_load_by_scenario_accepts_object_wrapper_and_normalizes_id(self) -> None:
        path = _write_json({"answers": [{"scenario_id": " Q082\n", "answer": "ok"}]})

        answers = _load_by_scenario(str(path), "answers")

        self.assertEqual(answers["Q082"]["scenario_id"], "Q082")

    def test_load_by_scenario_rejects_duplicate_ids(self) -> None:
        path = _write_json([{"scenario_id": "Q082"}, {"scenario_id": " Q082 "}])

        with self.assertRaisesRegex(ValueError, "duplicates scenario_id"):
            _load_by_scenario(str(path), "answers")

    def test_goldset_markdown_rejects_duplicate_ids(self) -> None:
        path = _write_text(
            "| ID | User Query | Expected Answer Shape | Ground Truth Answer |\n"
            "|---|---|---|---|\n"
            "| Q082 | first | shape | truth1 |\n"
            "| Q082 | second | shape | truth2 |\n"
        )

        with self.assertRaisesRegex(ValueError, "duplicate goldset scenario ID"):
            load_goldset_scenarios(str(path), {"Q082"})

    def test_answer_validation_rejects_missing_list_field(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unknowns.*required"):
            _validate_answer(
                {
                    "score": "Pass",
                    "failure_modes": ["none"],
                    "answer": "ok",
                    "score_reason": "ok",
                    "caveats": [],
                }
            )

    def test_answer_validation_rejects_contradictory_none_sentinel(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cannot combine"):
            _validate_answer(
                {
                    "score": "Pass",
                    "failure_modes": ["none", "bad synthesis"],
                    "answer": "ok",
                    "score_reason": "ok",
                    "caveats": [],
                    "unknowns": [],
                }
            )

    def test_judgement_validation_rejects_non_pass_with_none_sentinel(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "cannot use"):
            _validate_judgement(
                {
                    "evidence_completeness": "partial",
                    "answer_score": "Partial",
                    "failure_owners": ["none"],
                    "summary": "ok",
                    "recommended_next_action": "fix evidence",
                    "ground_truth_coverage": [],
                    "missing_or_weak_evidence": [],
                    "answer_issues": [],
                }
            )

    def test_parse_json_object_result_handles_prefixed_fenced_json(self) -> None:
        parsed = parse_json_object_result('Here is JSON:\n```json\n{"score": "Pass"}\n```', "test")

        self.assertEqual(parsed["score"], "Pass")

    def test_require_unique_strings_rejects_duplicates(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate value"):
            require_unique_strings(("Q082", "Q082"), "--scenario")

    def test_normalize_unique_strings_strips_before_duplicate_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate value"):
            normalize_unique_strings((" Q082 ", "Q082"), "--scenario")

    def test_resolve_claude_cli_path_rejects_bad_configured_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not executable"):
            resolve_claude_cli_path("/definitely/missing/claude")


def _write_json(value: object) -> Path:
    return _write_text(json.dumps(value))


def _write_text(value: str) -> Path:
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        path = Path(handle.name)
    path.write_text(value, encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
