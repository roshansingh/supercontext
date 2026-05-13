from __future__ import annotations

import unittest
from pathlib import Path

from source.kg.product.interactive_query import execute_interactive_plan, validate_interactive_plan


class InteractiveQueryTest(unittest.TestCase):
    def test_validate_plan_rejects_unsupported_anchor_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported retrieval anchor kind"):
            validate_interactive_plan({"anchors": [{"kind": "Service", "value": "payments"}]})

    def test_validate_plan_requires_anchor_clarification_or_refusal(self) -> None:
        with self.assertRaisesRegex(ValueError, "anchors, clarification, or refusal_reason"):
            validate_interactive_plan({"anchors": []})

    def test_validate_plan_accepts_clarification_without_anchors(self) -> None:
        plan = validate_interactive_plan({"anchors": [], "clarification": "Which package?"})

        self.assertEqual(plan["clarification"], "Which package?")
        self.assertEqual(plan["retrieval_steps"], [])

    def test_execute_plan_normalizes_list_results_into_evidence_packet(self) -> None:
        kg = _FakeKg()
        result = execute_interactive_plan(
            kg,
            user_query="What modules import sklearn?",
            plan={
                "anchors": [{"kind": "Package", "value": "sklearn"}],
                "answer_intent": "Find package importers.",
            },
        )

        self.assertEqual(result["plan"]["anchors"], [{"kind": "Package", "value": "sklearn"}])
        self.assertEqual(result["retrieval_steps"][0]["command"], "modules_importing")
        self.assertEqual(result["step_results"][0]["result"]["status"], "found")
        self.assertEqual(result["packet"]["evidence_items"][0]["fact_type"], "IMPORTS")
        self.assertEqual(result["packet"]["evidence_items"][0]["path"], "pkg.py")

    def test_repo_dependency_list_results_use_dependency_packet_section(self) -> None:
        kg = _FakeKg()
        result = execute_interactive_plan(
            kg,
            user_query="What does backend depend on?",
            plan={
                "anchors": [{"kind": "Repo", "value": "backend"}],
                "answer_intent": "Find repo dependencies.",
            },
        )

        self.assertEqual(result["step_results"][0]["result"]["status"], "found")
        self.assertIn("dependencies", result["step_results"][0]["result"])
        self.assertEqual(result["packet"]["evidence_items"][0]["fact_type"], "RESOLVES_TO_REPO")

    def test_no_private_corpus_tokens_in_interactive_modules(self) -> None:
        paths = [
            Path("source/kg/agent/interactive.py"),
            Path("source/kg/product/interactive_query.py"),
            Path("source/scripts/streamlit_app.py"),
        ]
        text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

        for token in ("examples/private-goldset", "private-goldset"):
            self.assertNotIn(token, text.lower())


class _FakeKg:
    def summary(self) -> dict[str, object]:
        return {
            "entity_counts": {"ExternalPackage": 1},
            "predicate_counts": {"IMPORTS": 1},
            "coverage_count": 1,
        }

    def modules_importing(self, package: str, limit: int = 25) -> list[dict[str, object]]:
        self._assert_package(package)
        return [
            {
                "fact_id": "fact_1",
                "predicate": "IMPORTS",
                "subject": "pkg.module",
                "object": "scikit-learn",
                "qualifier": {
                    "category": "third_party",
                    "distribution_name": "scikit-learn",
                    "import_root": "sklearn",
                },
                "evidence": [
                    {
                        "source_system": "static",
                        "derivation_class": "deterministic_static",
                        "confidence": 1.0,
                        "bytes_ref": {
                            "repo": "repo",
                            "commit_sha": "sha",
                            "path": "pkg.py",
                            "line_start": 3,
                            "line_end": 3,
                        },
                    }
                ],
            }
        ][:limit]

    def repo_dependencies(self, repo: str, limit: int = 25) -> list[dict[str, object]]:
        if repo != "backend":
            raise AssertionError(repo)
        return [
            {
                "fact_id": "fact_repo_1",
                "predicate": "RESOLVES_TO_REPO",
                "subject": "shared-client",
                "object": "shared-client-repo",
                "qualifier": {"package_name": "shared-client"},
                "evidence": [],
            }
        ][:limit]

    def _assert_package(self, package: str) -> None:
        if package != "sklearn":
            raise AssertionError(package)


if __name__ == "__main__":
    unittest.main()
