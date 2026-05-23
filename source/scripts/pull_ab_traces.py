from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull BetterContext A/B LangSmith traces into local JSONL.")
    parser.add_argument("--project", required=True, help="LangSmith project name.")
    parser.add_argument("--run-group-ids", default="", help="Comma-separated run_group_id values to pull.")
    parser.add_argument("--harness-version", default="", help="Optional harness_version metadata filter.")
    parser.add_argument("--out", required=True, help="Output JSONL path, usually under data/ab_runs/<run-id>/.")
    args = parser.parse_args()

    run_group_ids = {item.strip() for item in args.run_group_ids.split(",") if item.strip()}
    if not run_group_ids and not args.harness_version:
        parser.error("provide --run-group-ids or --harness-version")

    try:
        from langsmith import Client
    except ImportError as exc:
        raise RuntimeError("langsmith is required. Install with `pip install -e '.[eval]'`.") from exc

    client = Client()
    traces = []
    for run in client.list_runs(project_name=args.project, is_root=True):
        trace = trace_from_langsmith_run(run)
        if trace.get("arm") not in {"mcp_on", "mcp_off"}:
            continue
        if run_group_ids and trace.get("run_group_id") not in run_group_ids:
            continue
        if args.harness_version and trace.get("harness_version") != args.harness_version:
            continue
        traces.append(trace)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for trace in traces:
            stream.write(json.dumps(trace, sort_keys=True) + "\n")


def trace_from_langsmith_run(run: Any) -> dict[str, Any]:
    metadata = _metadata(run)
    total_cost = getattr(run, "total_cost", None)
    trace = {
        "id": str(getattr(run, "id", "")),
        "name": getattr(run, "name", ""),
        "run_type": getattr(run, "run_type", ""),
        "tags": list(getattr(run, "tags", []) or []),
        "metadata": metadata,
        "inputs": getattr(run, "inputs", None) or {},
        "outputs": getattr(run, "outputs", None) or {},
        "total_cost": total_cost,
        "prompt_cost": getattr(run, "prompt_cost", None),
        "completion_cost": getattr(run, "completion_cost", None),
        "total_tokens": getattr(run, "total_tokens", None),
        "prompt_tokens": getattr(run, "prompt_tokens", None),
        "completion_tokens": getattr(run, "completion_tokens", None),
        "cost_status": "available" if total_cost is not None else "unavailable",
    }
    for key in (
        "run_group_id",
        "arm",
        "task_id",
        "phase",
        "host",
        "repo_fixture",
        "difficulty",
        "harness_version",
        "task_prompt",
        "snapshot_path",
        "mcp_tools_called",
        "non_mcp_tools_called",
        "tokens_in",
        "tokens_out",
        "wall_time_seconds",
        "final_answer",
        "final_answer_citations",
        "model",
        "random_seed",
    ):
        trace[key] = metadata.get(key)
    return trace


def _metadata(run: Any) -> dict[str, Any]:
    extra = getattr(run, "extra", None) or {}
    metadata = extra.get("metadata") if isinstance(extra, dict) else None
    if isinstance(metadata, dict):
        return dict(metadata)
    return {}


if __name__ == "__main__":
    main()
