from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import yaml

from source.kg.eval.corpus import DEFAULT_QUERY_SET, _clean, default_v1_tasks, fixture_defaults_from_query_set, parse_query_set


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FIXTURE_OVERRIDES = ROOT / "docs/evaluation/default-v1-fixture-overrides.yaml"


class AbEvalCorpusTest(unittest.TestCase):
    def test_parser_reads_current_product_query_corpus(self) -> None:
        rows = parse_query_set(ROOT / DEFAULT_QUERY_SET)

        self.assertEqual(len(rows), 110)
        self.assertEqual(rows[0].task_id, "Q001")
        self.assertEqual(rows[-1].task_id, "Q110")
        self.assertEqual(Counter(row.difficulty for row in rows), {"Low": 15, "Medium": 40, "Hard": 55})
        self.assertEqual(len({row.task_id for row in rows}), 110)
        self.assertEqual(next(row for row in rows if row.task_id == "Q003").fixture, "$PY_REPO, $CALLER_SYMBOL")
        self.assertIsNotNone(next(row for row in rows if row.task_id == "Q001").golden)
        self.assertIsNotNone(next(row for row in rows if row.task_id == "Q081").golden)

    def test_default_v1_manifest_is_fixed_and_stratified(self) -> None:
        tasks = default_v1_tasks(query_set_path=ROOT / DEFAULT_QUERY_SET, seed=0)
        alternate_seed_tasks = default_v1_tasks(query_set_path=ROOT / DEFAULT_QUERY_SET, seed=1)

        self.assertEqual(len(tasks), 18)
        self.assertEqual(Counter(task.difficulty for task in tasks), {"Low": 4, "Medium": 6, "Hard": 8})
        self.assertEqual([task.task_id for task in tasks], [task.task_id for task in alternate_seed_tasks])
        self.assertEqual({task.phase for task in tasks}, {"planning", "coding", "review"})
        q037 = next(task for task in tasks if task.task_id == "Q037")
        self.assertIn('"changed_files"', q037.fixture_input)
        self.assertIn('"changed_ranges"', q037.fixture_input)
        self.assertIn('"repo": "backend_api"', q037.fixture_input)
        q003 = next(task for task in tasks if task.task_id == "Q003")
        self.assertEqual(q003.fixture, "mercury_ml, load_model")
        self.assertEqual(q003.prompt, "Who calls `load_model`?")
        self.assertIn(("$CALLER_SYMBOL", "load_model"), q003.fixture_bindings)
        q011 = next(task for task in tasks if task.task_id == "Q011")
        self.assertEqual(q011.prompt, "What service identity and URN did this repo produce?")
        self.assertIn(("$PY_REPO", "mercury_ml"), q011.fixture_bindings)
        q035 = next(task for task in tasks if task.task_id == "Q035")
        self.assertEqual(q035.prompt, "Which Kubernetes deployable runs `$SERVICE`?")
        self.assertEqual(q035.fixture_input, "")
        q048 = next(task for task in tasks if task.task_id == "Q048")
        self.assertEqual(q048.fixture_input, "")

    def test_default_v1_private_fixture_overrides_are_applied(self) -> None:
        tasks = default_v1_tasks(
            query_set_path=ROOT / DEFAULT_QUERY_SET,
            fixture_overrides_path=PRIVATE_FIXTURE_OVERRIDES,
            seed=0,
        )

        q035 = next(task for task in tasks if task.task_id == "Q035")
        self.assertEqual(q035.prompt, "Which Kubernetes deployable runs `mercury-api`?")
        self.assertIn(("$SERVICE", "mercury-api"), q035.fixture_bindings)
        self.assertIn('"service": "mercury_api"', q035.fixture_input)
        q040 = next(task for task in tasks if task.task_id == "Q040")
        self.assertEqual(q040.prompt, "What must deploy before `mercury-api` can safely deploy this schema change?")
        q045 = next(task for task in tasks if task.task_id == "Q045")
        self.assertEqual(
            q045.prompt,
            "Which services depend on `la-mercury-ml` directly and indirectly up to depth 3?",
        )
        self.assertIn(("$SERVICE", "la-mercury-ml"), q045.fixture_bindings)
        self.assertIn('"service": "mercury_ml"', q045.fixture_input)
        q048 = next(task for task in tasks if task.task_id == "Q048")
        self.assertIn('"event_channel": "la-prod-twilio"', q048.fixture_input)

    def test_fixture_defaults_parse_only_concrete_values(self) -> None:
        defaults = fixture_defaults_from_query_set(ROOT / DEFAULT_QUERY_SET)

        self.assertEqual(defaults["$PY_REPO"], "mercury_ml")
        self.assertEqual(defaults["$CALLER_SYMBOL"], "load_model")
        self.assertEqual(defaults["$ENTRY_SYMBOL_LINE"], "70")
        self.assertNotIn("$SERVICE", defaults)

    def test_default_v1_rejects_manifest_rows_not_in_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "default_v1_bad.yaml"
            manifest.write_text(
                yaml.safe_dump({"tasks": [{"id": "Q999", "phase": "planning"} for _ in range(18)]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not exist in query set"):
                default_v1_tasks(query_set_path=ROOT / DEFAULT_QUERY_SET, manifest_path=manifest)

    def test_default_v1_rejects_malformed_fixture_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "default_v1_bad.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "tasks": [
                            {"id": "Q003", "phase": "coding", "fixture_bindings": {"SERVICE": "mercury-api"}},
                            {"id": "Q004", "phase": "coding"},
                            {"id": "Q011", "phase": "planning"},
                            {"id": "Q015", "phase": "planning"},
                            {"id": "Q016", "phase": "coding"},
                            {"id": "Q021", "phase": "review"},
                            {"id": "Q031", "phase": "planning"},
                            {"id": "Q035", "phase": "planning"},
                            {"id": "Q051", "phase": "coding"},
                            {"id": "Q054", "phase": "planning"},
                            {"id": "Q037", "phase": "review"},
                            {"id": "Q038", "phase": "planning"},
                            {"id": "Q040", "phase": "review"},
                            {"id": "Q045", "phase": "planning"},
                            {"id": "Q048", "phase": "review"},
                            {"id": "Q053", "phase": "review"},
                            {"id": "Q081", "phase": "planning"},
                            {"id": "Q110", "phase": "review"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "fixture binding key"):
                default_v1_tasks(query_set_path=ROOT / DEFAULT_QUERY_SET, manifest_path=manifest)

    def test_print_tasks_cli_outputs_default_v1_tasks(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "source.scripts.run_ab_eval",
                "--query-set",
                str(ROOT / DEFAULT_QUERY_SET),
                "--tasks",
                "default-v1",
                "--fixture-overrides",
                str(PRIVATE_FIXTURE_OVERRIDES),
                "--seed",
                "1",
                "--print-tasks",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 18)
        self.assertEqual(lines[0].split("\t"), ["Q003", "Low", "coding"])

    def test_explicit_task_cli_uses_manifest_phase(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "source.scripts.run_ab_eval",
                "--query-set",
                str(ROOT / DEFAULT_QUERY_SET),
                "--tasks",
                "Q003",
                "--print-tasks",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Q003\tLow\tcoding")

    def test_clean_strips_only_wrapping_backticks(self) -> None:
        self.assertEqual(_clean(" `foo` and `bar` "), "`foo` and `bar`")
        self.assertEqual(_clean(" `wrapped` "), "wrapped")
        self.assertEqual(_clean(" `$PY_REPO`, `$CALLER_SYMBOL` "), "$PY_REPO, $CALLER_SYMBOL")


if __name__ == "__main__":
    unittest.main()
