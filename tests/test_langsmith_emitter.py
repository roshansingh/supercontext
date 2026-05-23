from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from source.kg.eval.langsmith_emitter import emit_run
from source.kg.eval.runner import RunRecord
from source.scripts.run_ab_eval import _upload_to_langsmith


class FakeRunTree:
    roots: list["FakeRunTree"] = []

    def __init__(
        self,
        *,
        name: str,
        run_type: str = "chain",
        inputs: dict | None = None,
        outputs: dict | None = None,
        tags: list[str] | None = None,
        project_name: str | None = None,
        parent: "FakeRunTree" | None = None,
    ) -> None:
        self.name = name
        self.run_type = run_type
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.tags = tags or []
        self.project_name = project_name
        self.parent = parent
        self.children: list[FakeRunTree] = []
        self.metadata: dict = {}
        self.usage_metadata: dict | None = None
        self.posted = False
        self.patched = False
        if parent is None:
            self.roots.append(self)

    def add_metadata(self, metadata: dict) -> None:
        self.metadata.update(metadata)

    def create_child(
        self,
        *,
        name: str,
        run_type: str = "chain",
        inputs: dict | None = None,
        outputs: dict | None = None,
        tags: list[str] | None = None,
    ) -> "FakeRunTree":
        child = type(self)(
            name=name,
            run_type=run_type,
            inputs=inputs,
            outputs=outputs,
            tags=tags,
            project_name=self.project_name,
            parent=self,
        )
        self.children.append(child)
        return child

    def post(self) -> None:
        self.posted = True

    def end(self, *, outputs: dict, metadata: dict | None = None) -> None:
        self.outputs = outputs
        if metadata:
            self.metadata.update(metadata)

    def patch(self) -> None:
        self.patched = True

    def get_url(self) -> str:
        return f"https://smith.langchain.com/fake/{self.name}"


class LangSmithEmitterTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeRunTree.roots = []

    def test_emit_run_uploads_required_tags_metadata_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            messages_path = Path(tmp) / "messages.jsonl"
            messages_path.write_text(
                json.dumps({"type": "ResultMessage", "data": {"content": "done"}}) + "\n",
                encoding="utf-8",
            )
            record = _record(messages_path=messages_path)

            with patch.dict(
                os.environ,
                {"LANGSMITH_API_KEY": "test-key", "LANGSMITH_PROJECT": "bettercontext-ab-eval"},
                clear=False,
            ):
                url = emit_run(record, messages_path, run_tree_cls=FakeRunTree)

        self.assertEqual(url, "https://smith.langchain.com/fake/bettercontext.ab_eval.Q003.mcp_off")
        self.assertEqual(len(FakeRunTree.roots), 1)
        root = FakeRunTree.roots[0]
        self.assertTrue(root.posted)
        self.assertTrue(root.patched)
        self.assertNotIn("record", root.outputs)
        self.assertIn("arm:mcp_off", root.tags)
        self.assertIn("task_id:Q003", root.tags)
        self.assertEqual(root.project_name, "bettercontext-ab-eval")
        self.assertEqual(root.metadata["run_group_id"], "group-1")
        self.assertEqual(root.metadata["mcp_tools_called"], [])
        self.assertEqual(root.metadata["mcp_tool_denial_count"], 0)
        self.assertEqual(root.metadata["non_mcp_tool_attempt_count"], 1)
        self.assertNotIn("dollars_spent", root.metadata)

        child_names = [child.name for child in root.children]
        self.assertEqual(child_names, ["harness.task_start", "host.claude_code.messages", "harness.task_end"])
        self.assertEqual(root.children[2].outputs["mcp_tool_success_count"], 0)
        self.assertEqual(root.children[2].outputs["non_mcp_tool_attempt_count"], 1)
        llm_span = root.children[1]
        self.assertEqual(llm_span.run_type, "llm")
        self.assertEqual(llm_span.metadata["ls_provider"], "anthropic")
        self.assertEqual(llm_span.metadata["ls_model_name"], "claude-sonnet-4-5-20250929")
        self.assertEqual(
            llm_span.outputs["usage_metadata"],
            {"input_tokens": 10, "output_tokens": 15, "total_tokens": 25},
        )
        self.assertEqual(llm_span.metadata["usage_metadata"], llm_span.outputs["usage_metadata"])

    def test_emit_run_fails_closed_without_langsmith_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            messages_path = Path(tmp) / "messages.jsonl"
            messages_path.write_text("{}\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "LANGSMITH_API_KEY"):
                    emit_run(_record(messages_path=messages_path), messages_path, run_tree_cls=FakeRunTree)

    def test_emit_run_rejects_non_object_message_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            messages_path = Path(tmp) / "messages.jsonl"
            messages_path.write_text("[]\n", encoding="utf-8")

            with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}, clear=False):
                with self.assertRaisesRegex(ValueError, "expected object"):
                    emit_run(_record(messages_path=messages_path), messages_path, run_tree_cls=FakeRunTree)

    def test_emit_run_rejects_malformed_message_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            messages_path = Path(tmp) / "messages.jsonl"
            messages_path.write_text("{\n", encoding="utf-8")

            with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}, clear=False):
                with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                    emit_run(_record(messages_path=messages_path), messages_path, run_tree_cls=FakeRunTree)

    def test_upload_to_langsmith_rejects_missing_message_log_path(self) -> None:
        record = replace(_record(messages_path=Path("messages.jsonl")), host_session_log_path="")

        with self.assertRaisesRegex(RuntimeError, "messages log not captured"):
            _upload_to_langsmith(record)


def _record(*, messages_path: Path) -> RunRecord:
    return RunRecord(
        run_group_id="group-1",
        arm="mcp_off",
        task_id="Q003",
        phase="coding",
        host="claude_code",
        repo_fixture="$PY_REPO, $CALLER_SYMBOL",
        difficulty="Low",
        harness_version="ab-eval-v1",
        task_prompt="Who calls load_model?",
        snapshot_path="data/kg_runs/example",
        mcp_tools_called=[],
        non_mcp_tools_called=["Read"],
        non_mcp_tool_attempt_count=1,
        non_mcp_tool_attempts=["Read"],
        tokens_in=10,
        tokens_out=15,
        wall_time_seconds=1.25,
        final_answer="load_model is called by predict.",
        final_answer_citations=[],
        host_session_log_path=str(messages_path),
        model="claude-sonnet-4-5-20250929",
        random_seed=7,
    )


if __name__ == "__main__":
    unittest.main()
