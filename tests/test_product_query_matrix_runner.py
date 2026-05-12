from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from source.kg.product.validation_report import (
    _aggregate_matrix_status,
    _product_query_matrix,
    _product_query_rows,
    render_product_query_matrix_markdown,
)


class ProductQueryMatrixRunnerTest(unittest.TestCase):
    def test_product_query_rows_parse_multiple_table_shapes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q001 | Low | CLI | Engineer | `$PY_REPO` | What imports pandas? | Importers. | Imports. |",
                        "",
                        "| ID | Difficulty | Surface | Persona | Scope | User Query | Expected Answer Shape | Capability Tested | Goldset? | Ground Truth Answer |",
                        "|---|---|---|---|---|---|---|---|---|---|",
                        "| Q081 | Hard | Support / CLI | CTO | `latticeai` org | Runtime map? | Runtime topology. | Topology. | Yes | Ground truth. |",
                    ]
                ),
                encoding="utf-8",
            )

            rows = _product_query_rows(query_set)

        self.assertEqual([row["query_id"] for row in rows], ["Q001", "Q081"])
        self.assertEqual(rows[0]["fixture"], "`$PY_REPO`")
        self.assertEqual(rows[1]["fixture"], "`latticeai` org")
        self.assertTrue(rows[1]["goldset"])

    def test_product_query_matrix_combines_smoke_judgement_and_unmeasured_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q001 | Low | CLI | Engineer | `$PY_REPO` | What imports pandas? | Importers. | Imports. |",
                        "| Q002 | Medium | CLI | Engineer | `llm-app-stack` | Public corpus query? | Public result. | Multi-repo. |",
                        "| Q081 | Hard | Support / CLI | CTO | `latticeai` org | Runtime map? | Runtime topology. | Topology. |",
                    ]
                ),
                encoding="utf-8",
            )
            smoke_rows = [
                {
                    "query_id": "Q001",
                    "difficulty": "Low",
                    "corpus": "Mercury ML",
                    "snapshot": "data/kg_runs/mercury_ml",
                    "surface": "modules-importing",
                    "result": "pass",
                    "notes": "pandas importers: 3 rows",
                },
                {
                    "query_id": "Q081",
                    "difficulty": "Hard",
                    "corpus": "Private Goldset",
                    "snapshot": "data/kg_runs/private",
                    "surface": "domain-references",
                    "result": "pass",
                    "notes": "domain refs found",
                },
            ]
            goldset = {
                "scenarios": [
                    {
                        "scenario_id": "Q081",
                        "answer_score": "Partial",
                        "failure_owners": ["missing KG fact"],
                        "notes": "Missing deploy evidence.",
                    }
                ]
            }

            matrix = _product_query_matrix(query_set, smoke_rows, goldset)

        rows_by_id = {row["query_id"]: row for row in matrix["rows"]}
        self.assertEqual(matrix["query_count"], 3)
        self.assertEqual(matrix["measured_query_count"], 2)
        self.assertEqual(matrix["unmeasured_query_count"], 1)
        self.assertEqual(rows_by_id["Q001"]["status"], "pass")
        self.assertEqual(rows_by_id["Q081"]["status"], "partial")
        self.assertEqual(rows_by_id["Q081"]["failure_owners"], ["missing KG fact"])
        self.assertEqual(rows_by_id["Q081"]["harness"], "deterministic smoke, goldset judgement")
        self.assertEqual(rows_by_id["Q002"]["status"], "unmeasured")
        self.assertEqual(rows_by_id["Q002"]["corpus"], "llm-app-stack")
        self.assertEqual(rows_by_id["Q002"]["failure_owners"], ["coverage gap"])
        self.assertEqual(matrix["status_summary"], {"partial": 1, "pass": 1, "unmeasured": 1})
        self.assertEqual(matrix["failure_owner_summary"]["coverage gap"], 1)
        self.assertEqual(matrix["failure_owner_summary"]["missing KG fact"], 1)
        self.assertIn("bad synthesis", matrix["failure_owner_summary"])
        self.assertIn("bad ground truth", matrix["failure_owner_summary"])

    def test_product_query_matrix_buckets_unknown_fixtures_without_raw_markdown_labels(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q054 | Medium | CLI | Security | any repo | Is this code secure? | Refusal. | Scope refusal. |",
                    ]
                ),
                encoding="utf-8",
            )

            matrix = _product_query_matrix(query_set, [], {"scenarios": []})

        self.assertEqual(matrix["rows"][0]["corpus"], "Unspecified fixture")

    def test_product_query_matrix_disabled_path_does_not_report_external_measurements(self) -> None:
        smoke_rows = [
            {
                "query_id": "Q001",
                "difficulty": "Low",
                "corpus": "Mercury ML",
                "snapshot": "data/kg_runs/mercury_ml",
                "surface": "modules-importing",
                "result": "pass",
                "notes": "pandas importers: 3 rows",
            }
        ]
        goldset = {
            "scenarios": [
                {
                    "scenario_id": "Q081",
                    "answer_score": "Partial",
                    "failure_owners": ["missing KG fact"],
                    "notes": "Missing deploy evidence.",
                }
            ]
        }

        matrix = _product_query_matrix(None, smoke_rows, goldset)

        self.assertIsNone(matrix["product_query_set"])
        self.assertEqual(matrix["query_count"], 0)
        self.assertEqual(matrix["tuple_count"], 0)
        self.assertEqual(matrix["measured_query_count"], 0)
        self.assertEqual(matrix["unmeasured_query_count"], 0)
        self.assertEqual(matrix["rows"], [])
        self.assertEqual(matrix["status_summary"], {})

    def test_product_query_matrix_preserves_unmeasured_tuple_for_partial_multi_corpus_coverage(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q078 | Hard | CLI | Platform | both fixture orgs | Compare fixture coverage. | Coverage table. | Coverage. |",
                    ]
                ),
                encoding="utf-8",
            )
            smoke_rows = [
                {
                    "query_id": "Q078",
                    "difficulty": "Hard",
                    "corpus": "llm-app-stack",
                    "snapshot": "data/kg_runs/llm-app-stack",
                    "surface": "coverage",
                    "result": "pass",
                    "notes": "llm-app-stack measured",
                }
            ]

            matrix = _product_query_matrix(query_set, smoke_rows, {"scenarios": []})

        rows_by_corpus = {row["corpus"]: row for row in matrix["rows"]}
        self.assertEqual(matrix["query_count"], 1)
        self.assertEqual(matrix["tuple_count"], 2)
        self.assertEqual(matrix["measured_query_count"], 1)
        self.assertEqual(matrix["unmeasured_query_count"], 0)
        self.assertEqual(rows_by_corpus["llm-app-stack"]["status"], "pass")
        self.assertEqual(rows_by_corpus["otel-demo"]["status"], "unmeasured")
        self.assertEqual(matrix["status_summary"], {"pass": 1, "unmeasured": 1})

    def test_product_query_rows_reject_duplicate_ids(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q001 | Low | CLI | Engineer | repo | First? | Shape. | Capability. |",
                        "| Q001 | Low | CLI | Engineer | repo | Duplicate? | Shape. | Capability. |",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate product query ID 'Q001'"):
                _product_query_rows(query_set)

    def test_product_query_rows_reject_missing_query_table(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| Name | Owner |",
                        "|---|---|",
                        "| Payments | Platform |",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ID and Difficulty columns"):
                _product_query_rows(query_set)

    def test_product_query_rows_reject_empty_query_table(self) -> None:
        with TemporaryDirectory() as tmpdir:
            query_set = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            query_set.write_text(
                "\n".join(
                    [
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| TODO | Unknown | CLI | Engineer | repo | Placeholder? | Shape. | Capability. |",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "valid product query rows"):
                _product_query_rows(query_set)

    def test_matrix_status_precedence_covers_fail_and_refusal(self) -> None:
        self.assertEqual(_aggregate_matrix_status(["pass", "fail"]), "fail")
        self.assertEqual(_aggregate_matrix_status(["pass", "refused correctly"]), "refused correctly")

    def test_product_query_matrix_markdown_renders_summary_and_rows(self) -> None:
        report = {
            "generated_at": "2026-05-12T00:00:00Z",
            "product_query_matrix": {
                "product_query_set": None,
                "query_count": 1,
                "tuple_count": 1,
                "measured_query_count": 0,
                "unmeasured_query_count": 1,
                "measured_query_coverage_pct": 0.0,
                "harness_sources": [],
                "status_summary": {"unmeasured": 1},
                "difficulty_summary": {"Hard": 1},
                "failure_owner_summary": {"coverage gap": 1},
                "rows": [
                    {
                        "query_id": "Q076",
                        "difficulty": "Hard",
                        "corpus": "otel-demo",
                        "status": "unmeasured",
                        "failure_owners": ["coverage gap"],
                        "harness": "none",
                        "notes": "No executable harness exists.",
                    }
                ],
            },
        }

        rendered = render_product_query_matrix_markdown(report)

        self.assertIn("# Product Query Set Run", rendered)
        self.assertIn("Product query set: `disabled`", rendered)
        self.assertIn("Measured queries: 0 / 1", rendered)
        self.assertIn("| Q076 | Hard | otel-demo | unmeasured | coverage gap | none | No executable harness exists. |", rendered)


if __name__ == "__main__":
    unittest.main()
