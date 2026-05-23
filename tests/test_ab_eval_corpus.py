from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import yaml

from source.kg.eval.corpus import DEFAULT_QUERY_SET, _clean, default_v1_tasks, parse_query_set


ROOT = Path(__file__).resolve().parents[1]


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

    def test_default_v1_rejects_manifest_rows_not_in_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "default_v1_bad.yaml"
            manifest.write_text(
                yaml.safe_dump({"tasks": [{"id": "Q999", "phase": "planning"} for _ in range(18)]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not exist in query set"):
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
