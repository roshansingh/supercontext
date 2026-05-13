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
        self.find_callees_calls: list[tuple[str, str | None, int | None]] = []
        self.dependency_path_calls: list[tuple[str, str, str | None, int | None]] = []

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
        if package_name == "os":
            return [{"name": "os", "category": "stdlib", "distribution_name": None}]
        if package_name == "sklearn":
            return [{"name": "sklearn", "distribution_name": None}]
        return [{"name": package_name, "distribution_name": package_name}]

    def find_callers(self, symbol: str, limit: int = 25) -> dict[str, object]:
        if symbol == "load_model":
            return {
                "status": "ambiguous",
                "target": {
                    "candidates": [
                        {"qualified_name": "HumanHandoverAgentDspy.load_model"},
                        {"qualified_name": "FrustrationPredictor.load_model"},
                    ]
                },
                "callers": [],
            }
        if symbol == "write_result_on_disk":
            return {"status": "found", "caller_count": 1, "callers": [{"subject": "predict_on_session"}]}
        return {"status": "not_found", "caller_count": 0, "callers": []}

    def find_callees(
        self,
        symbol: str,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
    ) -> dict[str, object]:
        self.find_callees_calls.append((symbol, path, line))
        if symbol == "predict_on_session" and path == "mercury_ml/intent_based_predictions/batch_predict.py" and line == 70:
            callees = [{"object": "build_features"}, {"object": "write_result_on_disk"}]
            return {"status": "found", "callee_count": len(callees), "returned_count": len(callees), "callees": callees}
        return {"status": "ambiguous", "callee_count": 0, "returned_count": 0, "callees": []}

    def who_imports(self, target: str, limit: int = 25) -> dict[str, object]:
        if target == "mercury_ml.chatbot.apis.openai_instructor":
            importers = [{"module": "duplicate_agent"}, {"module": "hallucination_detector"}]
            return {
                "status": "resolved",
                "importer_count": len(importers),
                "returned_count": len(importers),
                "importers": importers,
            }
        return {"status": "not_found", "importer_count": 0, "returned_count": 0, "importers": []}

    def modules_importing_both(self, left: str, right: str, limit: int = 25) -> dict[str, object]:
        if (left, right) == ("pandas", "sklearn"):
            return {"status": "resolved", "module_count": 1, "modules": [{"module": "train"}]}
        return {"status": "not_found", "module_count": 0, "modules": []}

    def dependency_path(
        self,
        source_query: str,
        target_query: str,
        path: str | None = None,
        line: int | None = None,
        limit: int = 5,
    ) -> dict[str, object]:
        self.dependency_path_calls.append((source_query, target_query, path, line))
        if (
            source_query == "predict_on_session"
            and target_query == "sklearn"
            and path == "mercury_ml/intent_based_predictions/batch_predict.py"
            and line == 70
        ):
            return {"status": "resolved", "path_count": 1, "paths": [{"nodes": ["predict_on_session", "sklearn"]}]}
        return {"status": "ambiguous", "path_count": 0, "paths": []}


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

    def test_q003_caller_symbol_binding_preserves_default_ambiguity_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q003 | Low | CLI | Engineer | `$PY_REPO`, `$CALLER_SYMBOL` | "
                    "Who calls `$CALLER_SYMBOL`? | Ambiguity response. | Symbol lookup. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("load_model default caller lookup status: ambiguous", row["notes"])

    def test_q004_entry_symbol_binding_disambiguates_with_fixture_coordinate(self) -> None:
        kg = FakeKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q004 | Low | CLI | Engineer | `$PY_REPO`, `$ENTRY_SYMBOL` | "
                    "What does `$ENTRY_SYMBOL` call directly? | Direct callees. | Calls. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(
            kg.find_callees_calls,
            [("predict_on_session", "mercury_ml/intent_based_predictions/batch_predict.py", 70)],
        )
        self.assertEqual(row["status"], "pass")
        self.assertIn("predict_on_session direct callees: 2 rows", row["notes"])

    def test_q004_entry_symbol_binding_fails_closed_without_resolved_callee_rows(self) -> None:
        class NoCalleesKg(FakeKg):
            def find_callees(
                self,
                symbol: str,
                limit: int = 25,
                path: str | None = None,
                line: int | None = None,
            ) -> dict[str, object]:
                self.find_callees_calls.append((symbol, path, line))
                return {"status": "ambiguous", "callee_count": 0, "callees": []}

        kg = NoCalleesKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q004 | Low | CLI | Engineer | `$PY_REPO`, `$ENTRY_SYMBOL` | "
                    "What does `$ENTRY_SYMBOL` call directly? | Direct callees. | Calls. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "fail")
        self.assertEqual(row["failure_owners"], ["missing KG fact"])

    def test_q008_stdlib_binding_checks_dependency_classification(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q008 | Low | CLI | Engineer | `$PY_REPO`, `os` | "
                    "Is `os` third-party or standard library usage? | Stdlib classification. | Import normalization. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("os stdlib dependency rows: 1 row", row["notes"])

    def test_q008_stdlib_binding_fails_closed_without_stdlib_classification(self) -> None:
        class MissingStdlibKg(FakeKg):
            def dependency_info(self, package_name: str) -> list[dict[str, object]]:
                if package_name == "os":
                    return [{"name": "os", "category": "third_party", "distribution_name": "os"}]
                return super().dependency_info(package_name)

        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q008 | Low | CLI | Engineer | `$PY_REPO`, `os` | "
                    "Is `os` third-party or standard library usage? | Stdlib classification. | Import normalization. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": MissingStdlibKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "fail")
        self.assertEqual(row["failure_owners"], ["missing KG fact"])

    def test_q013_write_result_binding_uses_reverse_call_lookup(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q013 | Low | CLI | Engineer | `$PY_REPO`, `write_result_on_disk` | "
                    "What are the direct callers of this symbol? | Caller symbols. | Reverse calls. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("write_result_on_disk direct callers: 1 row", row["notes"])

    def test_q017_internal_module_binding_uses_who_imports(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q017 | Medium | Support / IDE | Engineer | `$INTERNAL_MODULE` | "
                    "If I change this internal module, which modules import it? | Importers. | who-imports. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("mercury_ml.chatbot.apis.openai_instructor importers: 2 rows", row["notes"])

    def test_q023_dependency_intersection_binding_uses_existing_query_surface(self) -> None:
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q023 | Medium | CLI | Engineer | `$PY_REPO` | "
                    "Which modules combine `pandas` and `sklearn` usage? | Modules importing both. | Import intersections. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": FakeKg()},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(row["status"], "pass")
        self.assertIn("modules importing pandas and sklearn: 1 row", row["notes"])

    def test_q026_dependency_path_binding_disambiguates_with_fixture_coordinate(self) -> None:
        kg = FakeKg()
        with TemporaryDirectory() as tmpdir:
            matrix = _product_query_matrix(
                _query_set(
                    tmpdir,
                    "| Q026 | Medium | CLI | Engineer | `$ENTRY_SYMBOL`, `sklearn` | "
                    "What dependency path connects this symbol to `sklearn`, if any? | Path. | Path search. |",
                ),
                [],
                {"scenarios": []},
                {"Mercury ML": kg},  # type: ignore[dict-item]
            )

        row = matrix["rows"][0]
        self.assertEqual(
            kg.dependency_path_calls,
            [("predict_on_session", "sklearn", "mercury_ml/intent_based_predictions/batch_predict.py", 70)],
        )
        self.assertEqual(row["status"], "pass")
        self.assertIn("predict_on_session to sklearn dependency paths: 1 row", row["notes"])

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
                "| `$ENTRY_SYMBOL` | `predict_on_session` | Function/method with outgoing calls. |",
                "| `$CALLER_SYMBOL` | `load_model` | Ambiguous symbol fixture. |",
                "| `$INTERNAL_MODULE` | `mercury_ml.chatbot.apis.openai_instructor` | Internal module fixture. |",
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
