from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path

from source.scripts.coverage_metrics import METRICS_FILENAME, compare_metrics, main


class CoverageMetricsDeltaTest(unittest.TestCase):
    def test_compare_metrics_reports_per_metric_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(before, _record(value=0.25, state="usable"))
            _write_metrics(after, _record(value=0.75, state="usable"))

            deltas = compare_metrics(before, after)

            self.assertEqual(len(deltas), 1)
            self.assertEqual(deltas[0]["repo"], "repo")
            self.assertEqual(deltas[0]["dimension"], "backend")
            self.assertEqual(deltas[0]["metric"], "M_evidence_grounding")
            self.assertEqual(deltas[0]["value_delta"], 0.5)
            self.assertFalse(deltas[0]["state_changed"])

    def test_compare_cli_emits_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(
                before,
                _record(metric="M_evidence_grounding", value=0.25, state="usable"),
                _record(metric="M_trust_mix", value=0.5, state="usable"),
            )
            _write_metrics(
                after,
                _record(metric="M_evidence_grounding", value=None, state="n_a", reason="no facts"),
                _record(metric="M_trust_mix", value=0.75, state="usable"),
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--compare", str(before), str(after), "--json"])

            payloads = [json.loads(line) for line in stdout.getvalue().splitlines()]
            by_metric = {payload["metric"]: payload for payload in payloads}
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(payloads), 2)
            self.assertEqual(by_metric["M_evidence_grounding"]["value_delta"], None)
            self.assertTrue(by_metric["M_evidence_grounding"]["state_changed"])
            self.assertEqual(by_metric["M_evidence_grounding"]["after"]["reason"], "no facts")
            self.assertEqual(by_metric["M_trust_mix"]["value_delta"], 0.25)

    def test_compare_cli_rejects_snapshot_only_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(before, _record(value=0.25, state="usable"))
            _write_metrics(after, _record(value=0.75, state="usable"))

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(["--compare", str(before), str(after), "--expected-repos", "1"])
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(["--compare", str(before), str(after), "--expected-repos", "0"])

    def test_compare_reports_asymmetric_metric_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(before, _record(metric="M_evidence_grounding", value=0.25, state="usable"))
            _write_metrics(
                after,
                _record(metric="M_evidence_grounding", value=0.75, state="usable"),
                _record(metric="M_trust_mix", value=0.5, state="usable"),
            )

            deltas = {row["metric"]: row for row in compare_metrics(before, after)}

            self.assertIsNone(deltas["M_trust_mix"]["before"])
            self.assertEqual(deltas["M_trust_mix"]["after"]["value"], 0.5)
            self.assertIsNone(deltas["M_trust_mix"]["value_delta"])
            self.assertTrue(deltas["M_trust_mix"]["state_changed"])

    def test_compare_rejects_duplicate_metric_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(before, _record(value=0.25, state="usable"), _record(value=0.5, state="usable"))
            _write_metrics(after, _record(value=0.75, state="usable"))

            with self.assertRaisesRegex(ValueError, "duplicate metric key"):
                compare_metrics(before, after)

    def test_compare_rejects_malformed_metric_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = root / "before"
            after = root / "after"
            _write_metrics(before, _record(value=True, state="usable"))
            _write_metrics(after, _record(value=0.75, state="usable"))

            with self.assertRaisesRegex(ValueError, "value must be numeric"):
                compare_metrics(before, after)


def _write_metrics(snapshot: Path, *records: dict) -> None:
    snapshot.mkdir()
    with (snapshot / METRICS_FILENAME).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _record(
    *,
    metric: str = "M_evidence_grounding",
    value: float | bool | None,
    state: str,
    reason: str | None = None,
) -> dict:
    return {
        "repo": "repo",
        "dimension": "backend",
        "metric_values": {
            metric: {"value": value, "state": state, "reason": reason}
        },
        "cell_score": None,
        "contract_flags": [],
        "commit_sha_set": ["abc"],
        "built_at": "2026-05-17T00:00:00+00:00",
    }


if __name__ == "__main__":
    unittest.main()
