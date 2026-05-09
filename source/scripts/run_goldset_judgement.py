from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from source.kg.core.models import JsonObject
from source.kg.product.answer_synthesis import DEFAULT_ANSWER_MODEL
from source.kg.product.claude_tool_policy import DEFAULT_CLAUDE_PERMISSION_MODE
from source.kg.product.goldset_judgement import (
    ClaudeGoldsetJudge,
    GoldsetScenario,
    GoldsetJudgementConfig,
    load_goldset_scenarios,
    render_judgements_markdown,
)


DEFAULT_QUERY_SET = "docs/evaluation/PRODUCT-QUERY-SET.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Judge generated goldset answers against independent ground truth and KG evidence packets."
    )
    parser.add_argument("--query-set", default=DEFAULT_QUERY_SET, help="Markdown file containing ground truth rows")
    parser.add_argument("--packets", required=True, help="EvidencePacket JSON file")
    parser.add_argument("--answers", required=True, help="Synthesized answers JSON file")
    parser.add_argument("--scenario", action="append", help="Scenario ID to judge; repeatable. Defaults to all answers.")
    parser.add_argument("--json-out", help="Optional path to write judgement JSON")
    parser.add_argument("--md-out", help="Optional path to write judgement Markdown")
    parser.add_argument(
        "--model",
        default=os.getenv("CLAUDE_JUDGE_MODEL", DEFAULT_ANSWER_MODEL),
        help=f"Claude model for judgement. Defaults to {DEFAULT_ANSWER_MODEL}.",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=0.25,
        help="Maximum Claude API spend per scenario judgement call.",
    )
    parser.add_argument(
        "--load-timeout-ms",
        type=int,
        default=180_000,
        help="Claude Agent SDK load timeout in milliseconds.",
    )
    parser.add_argument(
        "--permission-mode",
        default=os.getenv(
            "CLAUDE_JUDGE_PERMISSION_MODE",
            os.getenv("CLAUDE_PERMISSION_MODE", DEFAULT_CLAUDE_PERMISSION_MODE),
        ),
        help=f"Claude Agent SDK permission mode. Defaults to {DEFAULT_CLAUDE_PERMISSION_MODE}.",
    )
    parser.add_argument(
        "--claude-cli-path",
        default=os.getenv("CLAUDE_JUDGE_CLI_PATH", os.getenv("CLAUDE_CLI_PATH")),
        help="Optional path to the Claude CLI. Defaults to resolving 'claude' on PATH.",
    )
    args = parser.parse_args()

    packets = _load_by_scenario(args.packets, "packets")
    answers = _load_by_scenario(args.answers, "answers")
    requested_scenario_ids = tuple(args.scenario or sorted(answers))
    scenarios = load_goldset_scenarios(args.query_set, set(requested_scenario_ids))
    missing = [scenario_id for scenario_id in requested_scenario_ids if scenario_id not in scenarios]
    if args.scenario and missing:
        raise ValueError(f"Missing ground truth for scenarios: {missing}")
    scenario_ids = tuple(scenario_id for scenario_id in requested_scenario_ids if scenario_id in scenarios)

    result = asyncio.run(
        _judge_all(
            query_set=args.query_set,
            packets_path=args.packets,
            answers_path=args.answers,
            scenario_ids=scenario_ids,
            scenarios=scenarios,
            packets=packets,
            answers=answers,
            skipped_missing_ground_truth=missing,
            config=GoldsetJudgementConfig(
                model=args.model,
                max_budget_usd=args.max_budget_usd,
                load_timeout_ms=args.load_timeout_ms,
                permission_mode=args.permission_mode,
                claude_cli_path=args.claude_cli_path,
            ),
        )
    )
    payload = json.dumps(result, indent=2, sort_keys=True)

    if args.json_out:
        _write_text(Path(args.json_out), payload + "\n")
    if args.md_out:
        _write_text(Path(args.md_out), render_judgements_markdown(result))
    if not args.json_out and not args.md_out:
        print(payload)


async def _judge_all(
    query_set: str,
    packets_path: str,
    answers_path: str,
    scenario_ids: tuple[str, ...],
    scenarios: dict[str, GoldsetScenario],
    packets: dict[str, JsonObject],
    answers: dict[str, JsonObject],
    skipped_missing_ground_truth: list[str],
    config: GoldsetJudgementConfig,
) -> JsonObject:
    judge = ClaudeGoldsetJudge(config)
    judgements = []
    for scenario_id in scenario_ids:
        if scenario_id not in packets:
            raise ValueError(f"Missing EvidencePacket for scenario {scenario_id}")
        if scenario_id not in answers:
            raise ValueError(f"Missing synthesized answer for scenario {scenario_id}")
        judgements.append(await judge.judge(scenarios[scenario_id], packets[scenario_id], answers[scenario_id]))

    return {
        "query_set": str(Path(query_set).expanduser()),
        "packets": str(Path(packets_path).expanduser()),
        "answers": str(Path(answers_path).expanduser()),
        "model": config.model,
        "scenario_count": len(judgements),
        "skipped_missing_ground_truth": skipped_missing_ground_truth,
        "judgements": judgements,
    }


def _load_by_scenario(path: str, key: str) -> dict[str, JsonObject]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    rows = data.get(key) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a list or an object with a {key!r} list")
    by_scenario: dict[str, JsonObject] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path} {key}[{index}] must be an object")
        scenario_id = row.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError(f"{path} {key}[{index}] must include a non-empty scenario_id")
        scenario_id = scenario_id.strip()
        if scenario_id in by_scenario:
            raise ValueError(f"{path} {key}[{index}] duplicates scenario_id {scenario_id!r}")
        by_scenario[str(scenario_id)] = row
    return by_scenario


def _write_text(path: Path, value: str) -> None:
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
