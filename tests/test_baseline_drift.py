from __future__ import annotations

import unittest
from pathlib import Path

from source.scripts.capture_snapshot_baseline import capture_snapshot_baseline
from source.scripts.compare_snapshot_baseline import load_baseline, compare_snapshot_baseline, render_differences


BASELINE_SNAPSHOTS = {
    "latticeai_23": Path("data/kg_runs/latticeai_23"),
    "llm-app-stack": Path("data/kg_runs/llm-app-stack"),
    "mercury_ml": Path("data/kg_runs/mercury_ml_eval_2026_05_11"),
    "otel-demo": Path("data/kg_runs/otel-demo"),
    "true_loop": Path("data/kg_runs/true_loop_eval_2026_05_11"),
}


class BaselineDriftTest(unittest.TestCase):
    def test_available_snapshots_match_committed_baselines(self) -> None:
        checked = 0
        failures: list[str] = []
        for name, snapshot in BASELINE_SNAPSHOTS.items():
            baseline_path = Path("tests/baselines/kg_counts") / f"{name}.json"
            if not _snapshot_available(snapshot):
                continue
            checked += 1
            with self.subTest(name=name):
                baseline = load_baseline(baseline_path)
                actual = capture_snapshot_baseline(snapshot, name=name)
                differences = compare_snapshot_baseline(actual, baseline)
                if differences:
                    failures.append(f"{name}\n{render_differences(differences)}")

        if checked == 0:
            self.skipTest("No KG snapshots are available under data/kg_runs; skipping baseline drift checks.")
        if failures:
            self.fail("\n\n".join(failures))


def _snapshot_available(path: Path) -> bool:
    return all(
        (path / filename).exists()
        for filename in ("manifest.json", "entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl")
    )


if __name__ == "__main__":
    unittest.main()
