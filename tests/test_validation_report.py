from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.product.validation_report import (
    ValidationConfig,
    _expect_count,
    _expect_list,
    _expect_status,
    _goldset_summary,
    _product_readout_lines,
    _run_smoke_checks,
    _superseded_artifacts,
    render_validation_markdown,
)


class ValidationReportTest(unittest.TestCase):
    def test_goldset_summary_classifies_judged_and_answer_only_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(
                json.dumps(
                    {
                        "packets": [
                            {"scenario_id": "Q001", "evidence_items": [{}], "retrieval_steps": [{}]},
                            {"scenario_id": "Q002", "evidence_items": [], "retrieval_steps": [{}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            answers.write_text(
                json.dumps({"answers": [{"scenario_id": "Q001", "score": "Pass"}, {"scenario_id": "Q002", "score": "Partial"}]}),
                encoding="utf-8",
            )
            judgement.write_text(
                json.dumps(
                    {
                        "judgements": [
                            {
                                "scenario_id": "Q001",
                                "evidence_completeness": "complete",
                                "answer_score": "Pass",
                                "failure_owners": ["none"],
                                "summary": "Useful answer.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        self.assertEqual(summary["answer_score_summary"], {"Pass": 1})
        self.assertEqual(summary["evidence_summary"], {"complete": 1})
        self.assertEqual(summary["answer_only_scenarios"], [{"scenario_id": "Q002", "self_score": "Partial", "notes": "No judgement ground truth available in PRODUCT-QUERY-SET."}])
        self.assertEqual(summary["packet_only_scenarios"], [])

    def test_goldset_summary_surfaces_packet_only_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(json.dumps({"packets": [{"scenario_id": "Q001"}, {"scenario_id": "Q002"}]}), encoding="utf-8")
            answers.write_text(json.dumps({"answers": [{"scenario_id": "Q001", "score": "Pass"}]}), encoding="utf-8")
            judgement.write_text(json.dumps({"judgements": []}), encoding="utf-8")

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        self.assertEqual(
            summary["packet_only_scenarios"],
            [{"scenario_id": "Q002", "notes": "EvidencePacket exists but no synthesized answer or judgement row was found."}],
        )

    def test_goldset_summary_rejects_duplicate_answer_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(json.dumps({"packets": [{"scenario_id": "Q001"}]}), encoding="utf-8")
            answers.write_text(
                json.dumps({"answers": [{"scenario_id": "Q001"}, {"scenario_id": "Q001"}]}),
                encoding="utf-8",
            )
            judgement.write_text(json.dumps({"judgements": []}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicates scenario_id"):
                _goldset_summary(_config(root, packets, answers, judgement))

    def test_markdown_marks_superseded_artifacts(self) -> None:
        report = {
            "generated_at": "2026-05-10T00:00:00Z",
            "status": "partial",
            "inputs": {"mercury_snapshot": "data/kg_runs/mercury"},
            "snapshot_inventory": [
                {"corpus": "Mercury", "snapshot": "data/kg_runs/mercury", "entities": 1, "facts": 2, "evidence": 3, "coverage": 4}
            ],
            "deterministic_smoke": {"summary": {"pass": 1}, "checks": []},
            "goldset": {
                "answer_score_summary": {"Pass": 1},
                "evidence_summary": {"complete": 1},
                "scenarios": [],
                "answer_only_scenarios": [],
                "packet_only_scenarios": [],
            },
            "next_feature_recommendation": "Next.",
            "supersedes": ["docs/evaluation/OLD|PIPE.md"],
        }

        markdown = render_validation_markdown(report)

        self.assertIn(r"docs/evaluation/OLD\|PIPE.md", markdown)
        self.assertIn("Superseded by this canonical report", markdown)

    def test_product_readout_is_derived_from_goldset_rows(self) -> None:
        goldset = {
            "scenarios": [
                {"scenario_id": "Q999", "answer_score": "Pass", "evidence_completeness": "complete", "failure_owners": ["none"]},
                {
                    "scenario_id": "Q998",
                    "answer_score": "Partial",
                    "evidence_completeness": "partial",
                    "failure_owners": ["missing KG fact"],
                },
            ]
        }

        lines = _product_readout_lines(goldset, "Next.")

        self.assertIn("Q999", lines[0])
        self.assertNotIn("Q082", lines[0])
        self.assertIn("missing KG fact=1", lines[1])

    def test_superseded_artifacts_are_generated_from_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evaluation = root / "docs" / "evaluation"
            evaluation.mkdir(parents=True)
            (evaluation / "CANONICAL-VALIDATION-REPORT.md").write_text("current", encoding="utf-8")
            (evaluation / "PRODUCT-QUERY-SET.md").write_text("active", encoding="utf-8")
            (evaluation / "README.md").write_text("active", encoding="utf-8")
            (evaluation / "LOW-QUERY-RUN-2026-05-06.md").write_text("old", encoding="utf-8")
            (evaluation / "LOW-QUERY-RERUN-IMPORT-NORMALIZATION-2026-05-06.md").write_text("old", encoding="utf-8")
            (evaluation / "NEXT-GAP-ANALYSIS-POST-PR17-2026-05-10.md").write_text("scratch", encoding="utf-8")

            artifacts = _superseded_artifacts(evaluation)

        self.assertEqual(
            artifacts,
            [
                f"{evaluation.as_posix()}/LOW-QUERY-RERUN-IMPORT-NORMALIZATION-2026-05-06.md",
                f"{evaluation.as_posix()}/LOW-QUERY-RUN-2026-05-06.md",
            ],
        )

    def test_superseded_artifacts_return_expanded_directory_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            evaluation = home / "evals"
            evaluation.mkdir()
            (evaluation / "LOW-QUERY-RUN-2026-05-06.md").write_text("old", encoding="utf-8")

            with patch.dict("os.environ", {"HOME": str(home)}):
                artifacts = _superseded_artifacts(Path("~") / "evals")

        self.assertEqual(artifacts, [f"{evaluation.as_posix()}/LOW-QUERY-RUN-2026-05-06.md"])

    def test_smoke_check_exceptions_fail_loud_in_strict_mode(self) -> None:
        def broken(_kg):
            raise KeyError("schema")

        with self.assertRaises(KeyError):
            _run_smoke_checks([("Corpus", Path("snapshot"), object(), [("Q999", "Low", "surface", "question", broken)])], strict=True)

    def test_smoke_check_exceptions_can_be_reported_in_non_strict_mode(self) -> None:
        def broken(_kg):
            raise KeyError("schema")

        rows = _run_smoke_checks([("Corpus", Path("snapshot"), object(), [("Q999", "Low", "surface", "question", broken)])], strict=False)

        self.assertEqual(rows[0]["result"], "fail")
        self.assertIn("KeyError", rows[0]["notes"])

    def test_expect_helpers_report_status_count_and_list_results(self) -> None:
        status_result, _, status_actual = _expect_status(lambda _kg: {"status": "resolved"}, "resolved")(object())
        count_result, _, count_actual = _expect_count(lambda _kg: {"matches": [{}, {}]}, "match_count", 2)(object())
        list_result, _, list_actual = _expect_list("rows", lambda _kg: [{"id": 1}], 1)(object())

        self.assertEqual(status_result, "pass")
        self.assertEqual(status_actual, {"status": "resolved"})
        self.assertEqual(count_result, "pass")
        self.assertEqual(count_actual, {"match_count": 2})
        self.assertEqual(list_result, "pass")
        self.assertEqual(list_actual["row_count"], 1)


def _config(root: Path, packets: Path, answers: Path, judgement: Path) -> ValidationConfig:
    return ValidationConfig(
        mercury_snapshot=root / "mercury",
        true_loop_snapshot=root / "true_loop",
        lattice_snapshot=root / "lattice",
        goldset_packets=packets,
        goldset_answers=answers,
        goldset_judgement=judgement,
        generated_at="2026-05-10T00:00:00Z",
        evaluation_dir=root / "docs" / "evaluation",
    )


if __name__ == "__main__":
    unittest.main()
