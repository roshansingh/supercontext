from __future__ import annotations

import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.scripts import judge_ab_quality


class FakeJudgeClient:
    prompts: list[str] = []

    def __init__(self, model: str) -> None:
        self.model = model

    def respond(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"winner": "A", "confidence": 0.8, "reasoning": "A is more correct."})


class FencedJudgeClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def respond(self, prompt: str) -> str:
        return '```json\n{"winner":"tie","confidence":0.5,"reasoning":"Both are equivalent."}\n```'


class InlineFencedJudgeClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def respond(self, prompt: str) -> str:
        return '```json {"winner":"B","confidence":0.7,"reasoning":"B has stronger evidence."}\n```'


class BadJudgeClient:
    def __init__(self, model: str) -> None:
        self.model = model

    def respond(self, prompt: str) -> str:
        return "not json"


class JudgeAbQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeJudgeClient.prompts = []

    def test_judge_rows_blinds_arm_labels_and_maps_winner(self) -> None:
        rows = [_delta_row()]

        judged = judge_ab_quality.judge_rows(rows, judge_model="judge-test", seed=1, client_factory=FakeJudgeClient)

        self.assertEqual(judged[0]["quality_verdict"], "judged")
        self.assertIn(judged[0]["judge_winner"], {"mcp_on", "mcp_off"})
        self.assertEqual(judged[0]["judge_confidence"], 0.8)
        prompt = FakeJudgeClient.prompts[0]
        self.assertNotIn("mcp_on", prompt)
        self.assertNotIn("mcp_off", prompt)

    def test_prompt_order_changes_with_seed(self) -> None:
        row = _delta_row(on_answer="on answer", off_answer="off answer")
        prompt_one, _ = judge_ab_quality.build_judge_prompt(row, rng=random.Random(1))
        prompt_five, _ = judge_ab_quality.build_judge_prompt(row, rng=random.Random(5))

        self.assertNotEqual(prompt_one, prompt_five)

    def test_fenced_judge_json_is_accepted(self) -> None:
        judged = judge_ab_quality.judge_rows([_delta_row()], judge_model="judge-test", client_factory=FencedJudgeClient)

        self.assertEqual(judged[0]["quality_verdict"], "judged")
        self.assertEqual(judged[0]["judge_winner"], "tie")

    def test_inline_fenced_judge_json_is_accepted(self) -> None:
        judged = judge_ab_quality.judge_rows(
            [_delta_row()],
            judge_model="judge-test",
            seed=1,
            client_factory=InlineFencedJudgeClient,
        )

        self.assertEqual(judged[0]["quality_verdict"], "judged")
        self.assertIn(judged[0]["judge_winner"], {"mcp_on", "mcp_off"})

    def test_bad_judge_response_marks_row_error_and_continues(self) -> None:
        judged = judge_ab_quality.judge_rows([_delta_row()], judge_model="judge-test", client_factory=BadJudgeClient)

        self.assertEqual(judged[0]["quality_verdict"], "judge_error")
        self.assertIn("valid JSON", judged[0]["judge_error"])

    def test_auto_quality_rows_are_preserved_without_judge_call(self) -> None:
        row = _delta_row()
        row["quality_verdict"] = "auto"

        judged = judge_ab_quality.judge_rows([row], judge_model="judge-test", client_factory=FakeJudgeClient)

        self.assertEqual(judged, [row])
        self.assertEqual(FakeJudgeClient.prompts, [])

    def test_judge_model_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            deltas = Path(tmp) / "deltas.jsonl"
            deltas.write_text(json.dumps(_delta_row()) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch("sys.argv", ["judge_ab_quality", "--deltas", str(deltas), "--out", str(Path(tmp) / "out.jsonl")]),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit),
            ):
                judge_ab_quality.main()
        self.assertIn("--judge-model", stderr.getvalue())


def _delta_row(*, on_answer: str = "on answer", off_answer: str = "off answer") -> dict:
    return {
        "task_id": "Q003",
        "phase": "coding",
        "quality_verdict": "ungraded",
        "on": {"answer": on_answer},
        "off": {"answer": off_answer},
    }


if __name__ == "__main__":
    unittest.main()
