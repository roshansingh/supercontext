from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from source.kg.product.validation_report import _product_query_matrix


class FakeKg:
    def __init__(self) -> None:
        self.coverage = [
            {
                "predicate": "PARSES",
                "state": "uninstrumented",
                "scope_ref": {"path": "mercury_ml/tests/intent_based_predictions/feature_builder_test.py"},
            }
        ]
        self.module_import_calls: list[str] = []

    def modules_importing(self, package_name: str, limit: int = 25) -> list[dict[str, object]]:
        self.module_import_calls.append(package_name)
        if package_name == "openai":
            return [
                {
                    "subject": "agents.malformed_import",
                    "object": "openai",
                    "qualifier": None,
                },
                {
                    "subject": "agents.duplicate_agent",
                    "object": "openai",
                    "qualifier": {"category": "third_party", "distribution_name": "openai"},
                }
            ]
        if package_name == "sklearn":
            return [
                {
                    "subject": "frustration_classification.train",
                    "object": "sklearn",
                    "qualifier": {"category": "unknown", "distribution_name": None},
                }
            ]
        return []

    def dependency_info(self, package_name: str) -> list[dict[str, object]]:
        if package_name == "sklearn":
            return [{"name": "sklearn", "distribution_name": None}]
        return [{"name": package_name, "distribution_name": package_name}]


class FixtureVariableBindingsTest(unittest.TestCase):
    def test_q002_package_binding_invokes_modules_importing(self) -> None:
        kg = FakeKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q002 | Low | CLI | Engineer | `$PY_REPO`, `$THIRD_PARTY_PACKAGE` | "
                    "What modules import `$THIRD_PARTY_PACKAGE` directly? | Importers. | Imports. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(kg.module_import_calls, ["openai"])
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["harness"], "fixture binding")
        self.assertIn("openai direct third-party importers", row["notes"])

    def test_q006_broken_file_binding_uses_coverage_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q006 | Low | CLI | Engineer | `$BROKEN_FILE` | "
                    "Which files could not be parsed or indexed? | Coverage rows. | Coverage. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("coverage rows for mercury_ml/tests/intent_based_predictions/feature_builder_test.py: 1", row["notes"])

    def test_inline_assignment_preserves_dotted_path_value(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q006 | Low | CLI | Engineer | `$BROKEN_FILE=mercury_ml/tests/intent_based_predictions/feature_builder_test.py` | "
                    "Which files could not be parsed or indexed? | Coverage rows. | Coverage. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("feature_builder_test.py: 1 rows", row["notes"])

    def test_q012_sklearn_binding_resolves_without_raw_fixture_fallback(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q012 | Low | CLI | Engineer | `$PY_REPO`, `sklearn` | "
                    "Which modules import `sklearn`? | Importers mapped to distribution. | Import alias mapping. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["corpus"], "Mercury ML")
        self.assertEqual(row["status"], "partial")
        self.assertEqual(row["failure_owners"], ["missing KG fact"])
        self.assertIn("sklearn importers: 1 rows; distribution mapping missing", row["notes"])

    def test_fixture_literal_comes_from_fixture_cell_without_package_allowlist(self) -> None:
        kg = FakeKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q012 | Low | CLI | Engineer | `$PY_REPO`, `torch` | "
                    "Which modules import a package? | Mentions `sklearn` outside fixture. | Import alias mapping. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(kg.module_import_calls, ["torch"])
        self.assertEqual(row["status"], "fail")
        self.assertIn("torch importers: 0 rows", row["notes"])

    def test_unresolved_variable_stays_unmeasured_with_specific_reason(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q050 | Medium | CLI | Engineer | `$XYZ` | "
                    "Can this unresolved fixture run? | Refusal. | Coverage. |",
                ),
                [],
                {"scenarios": []},
                {},
            )

        row = matrix["rows"][0]
        self.assertEqual(row["corpus"], "Unspecified fixture")
        self.assertEqual(row["status"], "unmeasured")
        self.assertEqual(row["notes"], "Fixture variable $XYZ has no binding for corpus Unspecified fixture.")

    def test_mercury_defaults_do_not_bind_unspecified_corpus_variables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q032 | Medium | CLI | Engineer | API repo fixture | "
                    "What endpoints does `$SERVICE` expose? | Endpoint list. | Endpoint extraction. |",
                ),
                [],
                {"scenarios": []},
                {},
            )

        row = matrix["rows"][0]
        self.assertEqual(row["corpus"], "Unspecified fixture")
        self.assertEqual(row["status"], "unmeasured")
        self.assertEqual(row["notes"], "Fixture variable $SERVICE has no binding for corpus Unspecified fixture.")

    def test_known_mercury_fixture_variables_route_to_mercury_corpus(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q018 | Medium | CLI | Engineer | `$THIRD_PARTY_PACKAGE=openai` | "
                    "Which code paths use OpenAI APIs indirectly? | Wrapper paths. | Imports plus calls. |",
                ),
                [],
                {"scenarios": []},
                {},
            )

        row = matrix["rows"][0]
        self.assertEqual(row["corpus"], "Mercury ML")
        self.assertEqual(row["status"], "unmeasured")

    def test_existing_smoke_measurement_takes_precedence_over_fixture_binding(self) -> None:
        kg = FakeKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q012 | Low | CLI | Engineer | `$PY_REPO`, `sklearn` | "
                    "Which modules import `sklearn`? | Importers mapped to distribution. | Import alias mapping. |",
                ),
                [
                    {
                        "query_id": "Q012",
                        "difficulty": "Low",
                        "corpus": "Mercury ML",
                        "snapshot": "data/kg_runs/mercury_ml",
                        "surface": "modules-importing",
                        "result": "pass",
                        "notes": "smoke importers passed",
                    }
                ],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(kg.module_import_calls, [])
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["failure_owners"], ["none"])
        self.assertEqual(row["harness"], "deterministic smoke")
        self.assertIn("smoke importers passed", row["notes"])

    def test_unquoted_fixture_defaults_are_supported(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            path.write_text(
                "\n".join(
                    [
                        "| Variable | Mercury v0 value | Portable meaning |",
                        "|---|---|---|",
                        "| `$PY_REPO` | mercury_ml | A Python repo fixture. |",
                        "| `$THIRD_PARTY_PACKAGE` | openai | External package dependency. |",
                        "",
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q002 | Low | CLI | Engineer | `$PY_REPO`, `$THIRD_PARTY_PACKAGE` | "
                        "What modules import `$THIRD_PARTY_PACKAGE` directly? | Importers. | Imports. |",
                    ]
                ),
                encoding="utf-8",
            )
            kg = FakeKg()
            matrix = _product_query_matrix(path, [], {"scenarios": []}, {"Mercury ML": kg})  # type: ignore[dict-item]

        self.assertEqual(kg.module_import_calls, ["openai"])
        self.assertEqual(matrix["rows"][0]["status"], "pass")

    def test_multi_value_fixture_default_does_not_guess_first_value(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
            path.write_text(
                "\n".join(
                    [
                        "| Variable | Mercury v0 value | Portable meaning |",
                        "|---|---|---|",
                        "| `$PY_REPO` | `mercury_ml` | A Python repo fixture. |",
                        "| `$SERVICE` | `payments` or `checkout-service` | Service fixture. |",
                        "",
                        "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                        "|---|---|---|---|---|---|---|---|",
                        "| Q032 | Medium | CLI | Engineer | `$PY_REPO`, `$SERVICE` | "
                        "What endpoints does `$SERVICE` expose? | Endpoint list. | Endpoint extraction. |",
                    ]
                ),
                encoding="utf-8",
            )

            matrix = _product_query_matrix(path, [], {"scenarios": []}, {"Mercury ML": FakeKg()})  # type: ignore[dict-item]

        row = matrix["rows"][0]
        self.assertEqual(row["corpus"], "Mercury ML")
        self.assertEqual(row["status"], "unmeasured")
        self.assertEqual(row["notes"], "Fixture variable $SERVICE has no binding for corpus Mercury ML.")


def _query_set(tmpdir: str, row: str) -> Path:
    path = Path(tmpdir) / "PRODUCT-QUERY-SET.md"
    path.write_text(
        "\n".join(
            [
                "| Variable | Mercury v0 value | Portable meaning |",
                "|---|---|---|",
                "| `$PY_REPO` | `mercury_ml` | A Python repo fixture. |",
                "| `$PACKAGE` | `pandas` | External package dependency. |",
                "| `$THIRD_PARTY_PACKAGE` | `openai` | External package dependency. |",
                "| `$BROKEN_FILE` | `mercury_ml/tests/intent_based_predictions/feature_builder_test.py` | File with parse coverage. |",
                "| `$SERVICE` | `payments` | Service fixture in multi-repo tests. |",
                "",
                "| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |",
                "|---|---|---|---|---|---|---|---|",
                row,
            ]
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
