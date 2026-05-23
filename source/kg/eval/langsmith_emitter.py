from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from source.kg.eval.runner import RunRecord


def emit_run(record: RunRecord, messages_path: str | Path, *, run_tree_cls: type[Any] | None = None) -> str:
    """Upload one local A/B run record and its captured SDK messages to LangSmith."""
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        raise RuntimeError("LANGSMITH_API_KEY is required to upload A/B eval traces to LangSmith.")

    resolved_messages_path = Path(messages_path)
    messages = _load_jsonl(resolved_messages_path)
    project_name = os.environ.get("LANGSMITH_PROJECT") or "bettercontext-ab-eval"
    run_tree_type = run_tree_cls or _load_run_tree_type()

    root = run_tree_type(
        name=f"bettercontext.ab_eval.{record.task_id}.{record.arm}",
        run_type="chain",
        inputs={
            "task_id": record.task_id,
            "task_prompt": record.task_prompt,
            "snapshot_path": record.snapshot_path,
            "messages_path": str(resolved_messages_path),
        },
        tags=_tags(record),
        project_name=project_name,
    )
    _add_metadata(root, _record_metadata(record, messages_path=resolved_messages_path))
    root.post()

    _finish_child(
        root,
        name="harness.task_start",
        run_type="chain",
        inputs={"run_group_id": record.run_group_id, "arm": record.arm, "task_id": record.task_id},
        outputs={"status": "started"},
    )

    llm_span = root.create_child(
        name="host.claude_code.messages",
        run_type="llm",
        inputs={"task_prompt": record.task_prompt, "messages_path": str(resolved_messages_path)},
        tags=_tags(record),
    )
    _add_metadata(llm_span, {"ls_provider": "anthropic", "ls_model_name": record.model})
    usage_metadata = _usage_metadata(record)
    llm_span.post()
    llm_outputs: dict[str, Any] = {"messages": messages, "final_answer": record.final_answer}
    llm_metadata: dict[str, Any] | None = None
    if usage_metadata:
        llm_outputs["usage_metadata"] = usage_metadata
        llm_metadata = {"usage_metadata": usage_metadata}
    llm_span.end(outputs=llm_outputs, metadata=llm_metadata)
    llm_span.patch()

    _finish_child(
        root,
        name="harness.task_end",
        run_type="chain",
        inputs={"run_group_id": record.run_group_id, "arm": record.arm, "task_id": record.task_id},
        outputs={
            "mcp_tools_called": record.mcp_tools_called,
            "non_mcp_tools_called": record.non_mcp_tools_called,
            "wall_time_seconds": record.wall_time_seconds,
            "cost_status": record.cost_status,
        },
    )

    root.end(outputs={"final_answer": record.final_answer, "record": record.to_json()})
    root.patch()
    return str(root.get_url())


def _load_run_tree_type() -> type[Any]:
    try:
        from langsmith.run_trees import RunTree
    except ImportError as exc:
        raise RuntimeError("langsmith is required for uploads. Install with `pip install -e '.[eval]'`.") from exc
    return RunTree


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"Messages JSONL path does not exist or is not a file: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on {path}:{line_number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Invalid message row on {path}:{line_number}: expected object")
        rows.append(row)
    return rows


def _tags(record: RunRecord) -> list[str]:
    return [
        f"arm:{record.arm}",
        f"task_id:{record.task_id}",
        f"phase:{record.phase}",
        f"host:{record.host}",
        f"repo_fixture:{record.repo_fixture}",
        f"difficulty:{record.difficulty}",
        f"harness_version:{record.harness_version}",
    ]


def _record_metadata(record: RunRecord, *, messages_path: Path) -> dict[str, Any]:
    metadata = record.to_json()
    metadata["messages_path"] = str(messages_path)
    return metadata


def _usage_metadata(record: RunRecord) -> dict[str, int]:
    usage: dict[str, int] = {}
    if record.tokens_in is not None:
        usage["input_tokens"] = record.tokens_in
    if record.tokens_out is not None:
        usage["output_tokens"] = record.tokens_out
    if usage:
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return usage


def _add_metadata(run: Any, metadata: dict[str, Any]) -> None:
    add_metadata = getattr(run, "add_metadata", None)
    if callable(add_metadata):
        add_metadata(metadata)
        return
    existing = getattr(run, "metadata", None)
    if isinstance(existing, dict):
        existing.update(metadata)
    else:
        setattr(run, "metadata", dict(metadata))


def _finish_child(
    root: Any,
    *,
    name: str,
    run_type: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
) -> Any:
    child = root.create_child(name=name, run_type=run_type, inputs=inputs)
    child.post()
    child.end(outputs=outputs)
    child.patch()
    return child
