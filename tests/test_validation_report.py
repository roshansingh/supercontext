from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.product.artifact_consistency import packet_fingerprint
from source.kg.product.validation_report import (
    ValidationConfig,
    _expect_count,
    _expect_list,
    _expect_status,
    _load_private_smoke_fixtures,
    _planned_goldset_scenarios,
    _private_fixture_smoke_checks,
    _goldset_summary,
    _overall_status,
    _product_readout_lines,
    _report_path,
    _run_smoke_checks,
    _superseded_artifacts,
    run_canonical_validation,
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
                json.dumps(
                    {
                        "answers": [
                            {
                                "scenario_id": "Q001",
                                "score": "Pass",
                                "evidence_item_count": 1,
                                "retrieval_step_count": 1,
                                "packet_fingerprint": packet_fingerprint(
                                    {"scenario_id": "Q001", "evidence_items": [{}], "retrieval_steps": [{}]}
                                ),
                            },
                            {"scenario_id": "Q002", "score": "Partial", "evidence_item_count": 0, "retrieval_step_count": 1},
                        ]
                    }
                ),
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
        self.assertEqual(summary["artifact_summary"], {"current": 1})
        self.assertEqual(summary["answer_only_scenarios"], [{"scenario_id": "Q002", "self_score": "Partial", "notes": "No judgement ground truth available in PRODUCT-QUERY-SET."}])
        self.assertEqual(summary["packet_only_scenarios"], [])
        self.assertEqual(summary["planned_scenario_count"], 0)
        self.assertEqual(summary["unrun_planned_scenarios"], [])
        self.assertEqual(summary["judged_but_not_planned_scenarios"], [])

    def test_goldset_summary_reports_unrun_planned_goldset_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            query_set = root / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Surface | Persona | Scope | User Query | Goldset? |",
                        "|---|---|---|---|---|---|---|",
                        "| Q001 | Medium | CLI | Engineer | repo | Covered question? | Yes |",
                        "| Q002 | Hard | CLI | SRE | org | Missing question? | Yes |",
                        "| Q003 | Hard | CLI | SRE | org | Non-gold question? | No |",
                    ]
                ),
                encoding="utf-8",
            )
            packets.write_text(json.dumps({"packets": [{"scenario_id": "Q001"}]}), encoding="utf-8")
            answers.write_text(
                json.dumps(
                    {
                        "answers": [
                            {
                                "scenario_id": "Q001",
                                "score": "Pass",
                                "packet_fingerprint": packet_fingerprint({"scenario_id": "Q001"}),
                            }
                        ]
                    }
                ),
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
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = _goldset_summary(_config(root, packets, answers, judgement, product_query_set=query_set))

        self.assertEqual(summary["planned_scenario_count"], 2)
        self.assertEqual(summary["planned_judged_count"], 1)
        self.assertEqual(
            summary["unrun_planned_scenarios"],
            [
                {
                    "scenario_id": "Q002",
                    "difficulty": "Hard",
                    "surface": "CLI",
                    "persona": "SRE",
                    "scope": "org",
                    "user_query": "Missing question?",
                }
            ],
        )
        self.assertEqual(summary["judged_but_not_planned_scenarios"], [])

    def test_goldset_summary_reports_judged_scenarios_not_marked_as_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            query_set = root / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Goldset? | User Query |",
                        "|---|---|---|",
                        "| Q001 | Yes | Planned. |",
                    ]
                ),
                encoding="utf-8",
            )
            packets.write_text(json.dumps({"packets": [{"scenario_id": "Q999"}]}), encoding="utf-8")
            answers.write_text(
                json.dumps(
                    {
                        "answers": [
                            {
                                "scenario_id": "Q999",
                                "score": "Pass",
                                "packet_fingerprint": packet_fingerprint({"scenario_id": "Q999"}),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            judgement.write_text(
                json.dumps(
                    {
                        "judgements": [
                            {
                                "scenario_id": "Q999",
                                "evidence_completeness": "complete",
                                "answer_score": "Pass",
                                "failure_owners": ["none"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = _goldset_summary(_config(root, packets, answers, judgement, product_query_set=query_set))

        self.assertEqual(summary["planned_judged_count"], 0)
        self.assertEqual(summary["unrun_planned_scenarios"][0]["scenario_id"], "Q001")
        self.assertEqual(summary["judged_but_not_planned_scenarios"], ["Q999"])

    def test_planned_goldset_scenarios_parse_markdown_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "queries.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Goldset? | User Query |",
                        "|---|---|---|",
                        "| Q010 | Yes | Keep this \\| escaped pipe. |",
                        "| Q011 | No | Skip this. |",
                        "| Q012 | yes | Keep lowercase yes. |",
                    ]
                ),
                encoding="utf-8",
            )

            planned = _planned_goldset_scenarios(query_set)

        self.assertEqual([row["scenario_id"] for row in planned], ["Q010", "Q012"])
        self.assertEqual(planned[0]["user_query"], "Keep this | escaped pipe.")

    def test_planned_goldset_scenarios_preserve_non_pipe_backslashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "queries.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Goldset? | User Query |",
                        "|---|---|---|",
                        r"| Q010 | Yes | Keep C:\tmp\file and \d regex. |",
                    ]
                ),
                encoding="utf-8",
            )

            planned = _planned_goldset_scenarios(query_set)

        self.assertEqual(planned[0]["user_query"], r"Keep C:\tmp\file and \d regex.")

    def test_planned_goldset_scenarios_reject_missing_query_set_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.md"

            with self.assertRaisesRegex(FileNotFoundError, "Product query set not found"):
                _planned_goldset_scenarios(missing)

    def test_planned_goldset_scenarios_reject_missing_required_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "queries.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| Scenario | Planned? | User Query |",
                        "|---|---|---|",
                        "| Q010 | Yes | Missing required headers. |",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ID and Goldset\\? columns"):
                _planned_goldset_scenarios(query_set)

    def test_planned_goldset_scenarios_reject_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "queries.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Goldset? | User Query |",
                        "|---|---|---|",
                        "| Q010 | Yes | First. |",
                        "| Q010 | Yes | Duplicate. |",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate planned goldset scenario ID 'Q010'"):
                _planned_goldset_scenarios(query_set)

    def test_goldset_summary_flags_stale_answer_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(
                json.dumps(
                    {"packets": [{"scenario_id": "Q088", "evidence_items": [{}, {}], "retrieval_steps": [{}, {}]}]}
                ),
                encoding="utf-8",
            )
            answers.write_text(
                json.dumps(
                    {
                        "answers": [
                            {"scenario_id": "Q088", "score": "Partial", "evidence_item_count": 1, "retrieval_step_count": 1}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            judgement.write_text(
                json.dumps(
                    {
                        "judgements": [
                            {
                                "scenario_id": "Q088",
                                "evidence_completeness": "partial",
                                "answer_score": "Partial",
                                "failure_owners": ["missing KG fact"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        self.assertEqual(summary["artifact_summary"], {"stale": 1})
        self.assertEqual(summary["scenarios"][0]["artifact_status"], "stale")
        self.assertEqual(
            summary["scenarios"][0]["artifact_issues"],
            [
                "answer missing packet_fingerprint; content freshness cannot be verified",
                "answer evidence_item_count=1 does not match current packet evidence_item_count=2",
                "answer retrieval_step_count=1 does not match current packet retrieval_step_count=2",
            ],
        )

    def test_goldset_summary_flags_stale_answer_when_fingerprint_changes_but_counts_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            current_packet = {"scenario_id": "Q088", "evidence_items": [{"id": "new"}], "retrieval_steps": [{"id": "same"}]}
            old_packet = {"scenario_id": "Q088", "evidence_items": [{"id": "old"}], "retrieval_steps": [{"id": "same"}]}
            packets.write_text(json.dumps({"packets": [current_packet]}), encoding="utf-8")
            answers.write_text(
                json.dumps(
                    {
                        "answers": [
                            {
                                "scenario_id": "Q088",
                                "score": "Pass",
                                "evidence_item_count": 1,
                                "retrieval_step_count": 1,
                                "packet_fingerprint": packet_fingerprint(old_packet),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            judgement.write_text(json.dumps({"judgements": [{"scenario_id": "Q088", "failure_owners": ["none"]}]}), encoding="utf-8")

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        self.assertEqual(summary["artifact_summary"], {"stale": 1})
        self.assertEqual(summary["scenarios"][0]["artifact_issues"], ["answer packet_fingerprint does not match current packet fingerprint"])

    def test_goldset_summary_flags_unverifiable_answer_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(
                json.dumps({"packets": [{"scenario_id": "Q088", "evidence_items": [], "retrieval_steps": []}]}),
                encoding="utf-8",
            )
            answers.write_text(json.dumps({"answers": [{"scenario_id": "Q088", "score": "Pass"}]}), encoding="utf-8")
            judgement.write_text(json.dumps({"judgements": [{"scenario_id": "Q088", "failure_owners": ["none"]}]}), encoding="utf-8")

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        self.assertEqual(summary["artifact_summary"], {"unverified": 1})
        self.assertEqual(summary["scenarios"][0]["artifact_status"], "unverified")

    def test_goldset_summary_flags_missing_packet_and_answer_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(
                json.dumps({"packets": [{"scenario_id": "Q001", "evidence_items": [], "retrieval_steps": []}]}),
                encoding="utf-8",
            )
            answers.write_text(
                json.dumps(
                    {"answers": [{"scenario_id": "Q002", "score": "Pass", "evidence_item_count": 0, "retrieval_step_count": 0}]}
                ),
                encoding="utf-8",
            )
            judgement.write_text(
                json.dumps(
                    {
                        "judgements": [
                            {"scenario_id": "Q001", "failure_owners": ["none"]},
                            {"scenario_id": "Q002", "failure_owners": ["none"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = _goldset_summary(_config(root, packets, answers, judgement))

        statuses = {row["scenario_id"]: row["artifact_status"] for row in summary["scenarios"]}
        self.assertEqual(statuses, {"Q001": "missing_answer", "Q002": "missing_packet"})
        self.assertEqual(summary["artifact_summary"], {"missing_answer": 1, "missing_packet": 1})

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

    def test_goldset_summary_rejects_non_object_judgement_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(json.dumps({"packets": []}), encoding="utf-8")
            answers.write_text(json.dumps({"answers": []}), encoding="utf-8")
            judgement.write_text(json.dumps([]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "object with a 'judgements' list"):
                _goldset_summary(_config(root, packets, answers, judgement))

    def test_goldset_summary_rejects_duplicate_judgement_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            packets = root / "packets.json"
            answers = root / "answers.json"
            judgement = root / "judgement.json"
            packets.write_text(json.dumps({"packets": [{"scenario_id": "Q001"}]}), encoding="utf-8")
            answers.write_text(json.dumps({"answers": [{"scenario_id": "Q001"}]}), encoding="utf-8")
            judgement.write_text(
                json.dumps(
                    {
                        "judgements": [
                            {"scenario_id": "Q001", "failure_owners": ["none"]},
                            {"scenario_id": "Q001", "failure_owners": ["none"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicates scenario_id 'Q001'"):
                _goldset_summary(_config(root, packets, answers, judgement))

    def test_goldset_summary_reports_expanded_metadata_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            packets = home / "packets.json"
            answers = home / "answers.json"
            judgement = home / "judgement.json"
            packets.write_text(json.dumps({"packets": []}), encoding="utf-8")
            answers.write_text(json.dumps({"answers": []}), encoding="utf-8")
            judgement.write_text(json.dumps({"judgements": []}), encoding="utf-8")

            with patch.dict("os.environ", {"HOME": str(home)}):
                summary = _goldset_summary(
                    _config(
                        home,
                        Path("~/packets.json"),
                        Path("~/answers.json"),
                        Path("~/judgement.json"),
                    )
                )

        self.assertEqual(summary["packets_path"], packets.resolve().as_posix())
        self.assertEqual(summary["answers_path"], answers.resolve().as_posix())
        self.assertEqual(summary["judgement_path"], judgement.resolve().as_posix())

    def test_run_canonical_validation_reports_expanded_input_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            config = _config(
                home,
                Path("~/packets.json"),
                Path("~/answers.json"),
                Path("~/judgement.json"),
            )
            config = ValidationConfig(
                mercury_snapshot=Path("~/mercury"),
                true_loop_snapshot=Path("~/true_loop"),
                private_snapshot=Path("~/private"),
                goldset_packets=config.goldset_packets,
                goldset_answers=config.goldset_answers,
                goldset_judgement=config.goldset_judgement,
                generated_at=config.generated_at,
                evaluation_dir=config.evaluation_dir,
                next_feature_recommendation="Operator-authored next step.",
            )

            with (
                patch.dict("os.environ", {"HOME": str(home)}),
                patch("source.kg.product.validation_report.KgSnapshot", return_value=object()),
                patch("source.kg.product.validation_report._run_smoke_checks", return_value=[]),
                patch(
                    "source.kg.product.validation_report._goldset_summary",
                    return_value={
                        "scenarios": [],
                        "answer_only_scenarios": [],
                        "packet_only_scenarios": [],
                    },
                ),
                patch("source.kg.product.validation_report._snapshot_inventory", return_value={}),
                patch("source.kg.product.validation_report._superseded_artifacts", return_value=[]),
            ):
                report = run_canonical_validation(config)

        self.assertEqual(report["inputs"]["mercury_snapshot"], (home / "mercury").resolve().as_posix())
        self.assertEqual(report["inputs"]["goldset_packets"], (home / "packets.json").resolve().as_posix())
        self.assertEqual(report["next_feature_recommendation"], "Operator-authored next step.")

    def test_private_smoke_fixture_absence_skips_private_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = _load_private_smoke_fixtures(Path(tmpdir) / "missing.json")

        self.assertIsNone(fixture)
        self.assertEqual(_private_fixture_smoke_checks(fixture), [])

    def test_private_smoke_fixture_values_drive_checks_without_source_literals(self) -> None:
        fixture = {
            "api_domain": "api.example.com",
            "token_endpoint_path": "/api/token",
            "primary_event_channel": "orders-events",
            "source_ref_event_channel": "status-events",
        }
        kg = _FakePrivateSmokeKg()

        checks = _private_fixture_smoke_checks(fixture)
        rows = _run_smoke_checks([("Private Fixture", Path("snapshot"), kg, checks)], strict=True)

        self.assertEqual(len(rows), 5)
        self.assertEqual({row["result"] for row in rows}, {"pass"})
        self.assertIn(("domain_references", "api.example.com"), kg.calls)
        self.assertIn(("event_channels", "orders-events"), kg.calls)
        self.assertIn(("event_channels", "status-events"), kg.calls)

    def test_private_smoke_fixture_rejects_malformed_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fixtures.json"
            path.write_text(json.dumps({"private_smoke": {"api_domain": ""}}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "api_domain"):
                _private_fixture_smoke_checks(_load_private_smoke_fixtures(path))

    def test_report_path_normalizes_repo_local_relative_segments(self) -> None:
        self.assertEqual(_report_path(Path("source") / ".." / "source"), "source")

    def test_markdown_marks_superseded_artifacts(self) -> None:
        report = {
            "generated_at": "2026-05-10T00:00:00Z",
            "status": "partial",
            "quality_status": "pass",
            "coverage_status": "partial",
            "inputs": {"mercury_snapshot": "data/kg_runs/mercury"},
            "snapshot_inventory": [
                {"corpus": "Mercury", "snapshot": "data/kg_runs/mercury", "entities": 1, "facts": 2, "evidence": 3, "coverage": 4}
            ],
            "deterministic_smoke": {"summary": {"pass": 1}, "checks": []},
            "goldset": {
                "answer_score_summary": {"Pass": 1},
                "evidence_summary": {"complete": 1},
                "artifact_summary": {"current": 1},
                "planned_scenario_count": 1,
                "planned_judged_count": 1,
                "unrun_planned_scenarios": [],
                "judged_but_not_planned_scenarios": [],
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
        self.assertIn("Quality status: **pass**", markdown)
        self.assertIn("Coverage status: **partial**", markdown)

    def test_render_validation_markdown_includes_goldset_plan_coverage(self) -> None:
        report = {
            "generated_at": "2026-05-10T00:00:00Z",
            "status": "partial",
            "quality_status": "pass",
            "coverage_status": "partial",
            "inputs": {},
            "snapshot_inventory": [],
            "deterministic_smoke": {"summary": {}, "checks": []},
            "goldset": {
                "answer_score_summary": {"Pass": 1},
                "evidence_summary": {"complete": 1},
                "artifact_summary": {"current": 1},
                "planned_scenario_count": 10,
                "planned_judged_count": 1,
                "unrun_planned_scenarios": [
                    {"scenario_id": f"Q00{index}", "user_query": f"Missing question {index}?"}
                    for index in range(2, 11)
                ],
                "judged_but_not_planned_scenarios": ["Q999"],
                "scenarios": [],
                "answer_only_scenarios": [],
                "packet_only_scenarios": [],
            },
            "next_feature_recommendation": "Next.",
            "supersedes": [],
        }

        markdown = render_validation_markdown(report)

        self.assertIn("Goldset plan coverage: 1 judged / 10 planned.", markdown)
        self.assertIn("Planned goldset scenarios not yet judged:", markdown)
        self.assertIn("`Q002`: Missing question 2?", markdown)
        self.assertIn("`Q009`: Missing question 9?", markdown)
        self.assertNotIn("`Q0010`: Missing question 10?", markdown)
        self.assertIn("...and 1 more planned scenario(s).", markdown)
        self.assertIn("Judged scenarios not marked as planned goldset:", markdown)
        self.assertIn("`Q999`", markdown)

    def test_product_readout_is_derived_from_goldset_rows(self) -> None:
        goldset = {
            "scenarios": [
                {
                    "scenario_id": "Q999",
                    "answer_score": "Pass",
                    "evidence_completeness": "complete",
                    "failure_owners": ["none"],
                    "artifact_status": "current",
                },
                {
                    "scenario_id": "Q998",
                    "answer_score": "Partial",
                    "evidence_completeness": "partial",
                    "failure_owners": ["missing KG fact"],
                    "artifact_status": "current",
                },
            ]
        }

        lines = _product_readout_lines(goldset, "Next.")

        self.assertIn("Q999", lines[0])
        self.assertNotIn("Q082", lines[0])
        self.assertIn("missing KG fact=1", lines[1])

    def test_product_readout_separates_stale_artifacts_from_product_failures(self) -> None:
        goldset = {
            "scenarios": [
                {
                    "scenario_id": "Q088",
                    "answer_score": "Partial",
                    "evidence_completeness": "partial",
                    "failure_owners": ["missing KG fact"],
                    "artifact_status": "stale",
                }
            ]
        }

        lines = _product_readout_lines(goldset, "Next.")
        joined_lines = "\n".join(lines)

        self.assertIn("Artifact consistency blocks product-gap diagnosis for Q088", joined_lines)
        self.assertIn("Suspected failure owners pending re-judgement: missing KG fact=1", joined_lines)
        self.assertNotIn("Remaining judged failures are concentrated in: missing KG fact=1", joined_lines)

    def test_overall_status_is_partial_for_incomplete_goldset_coverage(self) -> None:
        goldset = {
            "scenarios": [{"scenario_id": "Q001", "answer_score": "Pass"}],
            "answer_only_scenarios": [{"scenario_id": "Q002"}],
            "packet_only_scenarios": [],
        }

        self.assertEqual(_overall_status([], goldset), "partial")

        goldset["answer_only_scenarios"] = []
        goldset["packet_only_scenarios"] = [{"scenario_id": "Q003"}]

        self.assertEqual(_overall_status([], goldset), "partial")

        goldset["packet_only_scenarios"] = []
        goldset["unrun_planned_scenarios"] = [{"scenario_id": "Q004"}]

        self.assertEqual(_overall_status([], goldset), "partial")

    def test_overall_status_is_partial_for_unknown_judgement_score(self) -> None:
        goldset = {
            "scenarios": [{"scenario_id": "Q001", "answer_score": "unknown"}],
            "answer_only_scenarios": [],
            "packet_only_scenarios": [],
        }

        self.assertEqual(_overall_status([], goldset), "partial")

    def test_overall_status_does_not_fail_on_stale_judgement_failure(self) -> None:
        goldset = {
            "scenarios": [{"scenario_id": "Q001", "answer_score": "Fail", "artifact_status": "stale"}],
            "answer_only_scenarios": [],
            "packet_only_scenarios": [],
        }

        self.assertEqual(_overall_status([], goldset), "partial")

        goldset["scenarios"][0]["artifact_status"] = "current"
        self.assertEqual(_overall_status([], goldset), "fail")

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
            (evaluation / "GOLDSET-ARTIFACT-CONSISTENCY-TRIAGE-2026-05-10.md").write_text("old", encoding="utf-8")
            (evaluation / "LATTICEAI-GOLDSET-ANSWERS-Q100-PR16.md").write_text("old", encoding="utf-8")
            (evaluation / "NEXT-GAP-ANALYSIS-POST-PR17-2026-05-10.md").write_text("scratch", encoding="utf-8")
            (evaluation / "NOT-HISTORICAL-NOTE.md").write_text("scratch", encoding="utf-8")

            artifacts = _superseded_artifacts(evaluation)

        self.assertEqual(
            artifacts,
            [
                f"{evaluation.as_posix()}/GOLDSET-ARTIFACT-CONSISTENCY-TRIAGE-2026-05-10.md",
                f"{evaluation.as_posix()}/LATTICEAI-GOLDSET-ANSWERS-Q100-PR16.md",
                f"{evaluation.as_posix()}/LOW-QUERY-RERUN-IMPORT-NORMALIZATION-2026-05-06.md",
                f"{evaluation.as_posix()}/LOW-QUERY-RUN-2026-05-06.md",
                f"{evaluation.as_posix()}/NEXT-GAP-ANALYSIS-POST-PR17-2026-05-10.md",
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


def _config(
    root: Path,
    packets: Path,
    answers: Path,
    judgement: Path,
    product_query_set: Path | None = None,
) -> ValidationConfig:
    return ValidationConfig(
        mercury_snapshot=root / "mercury",
        true_loop_snapshot=root / "true_loop",
        private_snapshot=root / "private",
        goldset_packets=packets,
        goldset_answers=answers,
        goldset_judgement=judgement,
        generated_at="2026-05-10T00:00:00Z",
        product_query_set=product_query_set,
        evaluation_dir=root / "docs" / "evaluation",
    )


class _FakePrivateSmokeKg:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def domain_references(self, domain: str, limit: int) -> dict[str, object]:
        self.calls.append(("domain_references", domain))
        return {
            "reference_count": 1,
            "references": [{"predicate": "REFERENCES_ENV_VAR"}],
        }

    def endpoints(self, path_query: str, limit: int) -> dict[str, object]:
        self.calls.append(("endpoints", path_query))
        return {"endpoint_fact_count": 1}

    def event_channels(self, channel_query: str, limit: int) -> dict[str, object]:
        self.calls.append(("event_channels", channel_query))
        return {
            "event_fact_count": 1,
            "event_channels": [{"qualifier": {"resolution": {"source_refs": [{"path": "fixture.ini"}]}}}],
        }


if __name__ == "__main__":
    unittest.main()
