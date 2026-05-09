from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from source.kg.core.models import JsonObject
from source.kg.product import (
    SCENARIO_PLANS,
    AnswerSynthesisConfig,
    ClaudeAnswerSynthesizer,
    EvidencePacketBuilder,
)
from source.kg.product.answer_synthesis import DEFAULT_ANSWER_MODEL, render_answers_markdown
from source.kg.product.claude_tool_policy import DEFAULT_CLAUDE_PERMISSION_MODE
from source.kg.query.snapshot import KgSnapshot


DEFAULT_SCENARIOS = ("Q082", "Q083", "Q088", "Q095", "Q100", "Q106")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize product-validation answers from KG evidence packets.")
    parser.add_argument("--snapshot", required=True, help="Directory containing JSONL KG files")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIO_PLANS),
        help="Scenario ID to run; repeatable. Defaults to the LatticeAI goldset scenarios.",
    )
    parser.add_argument("--packets-in", help="Optional existing EvidencePacket JSON file")
    parser.add_argument("--packets-out", help="Optional path to write generated EvidencePacket JSON")
    parser.add_argument("--json-out", help="Optional path to write synthesized answers JSON")
    parser.add_argument("--md-out", help="Optional path to write synthesized answers Markdown")
    parser.add_argument(
        "--model",
        default=os.getenv("CLAUDE_ANSWER_MODEL", DEFAULT_ANSWER_MODEL),
        help=f"Claude model for answer synthesis. Defaults to {DEFAULT_ANSWER_MODEL}.",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=0.25,
        help="Maximum Claude API spend per scenario synthesis call.",
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
            "CLAUDE_ANSWER_PERMISSION_MODE",
            os.getenv("CLAUDE_PERMISSION_MODE", DEFAULT_CLAUDE_PERMISSION_MODE),
        ),
        help=f"Claude Agent SDK permission mode. Defaults to {DEFAULT_CLAUDE_PERMISSION_MODE}.",
    )
    parser.add_argument(
        "--claude-cli-path",
        default=os.getenv("CLAUDE_ANSWER_CLI_PATH", os.getenv("CLAUDE_CLI_PATH")),
        help="Optional path to the Claude CLI. Defaults to resolving 'claude' on PATH.",
    )
    args = parser.parse_args()

    scenario_ids = tuple(args.scenario or DEFAULT_SCENARIOS)
    packets = _load_or_build_packets(args.snapshot, scenario_ids, args.packets_in)
    if args.packets_out:
        _write_json(
            Path(args.packets_out),
            {"snapshot": str(Path(args.snapshot).expanduser()), "scenario_count": len(packets), "packets": packets},
        )

    result = asyncio.run(
        _synthesize_answers(
            args.snapshot,
            packets,
            AnswerSynthesisConfig(
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
        _write_text(Path(args.md_out), render_answers_markdown(result))
    if not args.json_out and not args.md_out:
        print(payload)


def _load_or_build_packets(
    snapshot: str,
    scenario_ids: tuple[str, ...],
    packets_in: str | None,
) -> list[JsonObject]:
    if packets_in:
        data = json.loads(Path(packets_in).expanduser().read_text(encoding="utf-8"))
        packets = data.get("packets") if isinstance(data, dict) else data
        if not isinstance(packets, list):
            raise ValueError("packets input must be a list or an object with a 'packets' list")
        scenario_id_set = set(scenario_ids)
        filtered_packets = []
        found_scenario_ids = set()
        for index, packet in enumerate(packets):
            if not isinstance(packet, dict):
                raise ValueError(f"{packets_in} packets[{index}] must be an object")
            scenario_id = packet.get("scenario_id")
            if not isinstance(scenario_id, str) or not scenario_id.strip():
                raise ValueError(f"{packets_in} packets[{index}] must include a non-empty scenario_id")
            scenario_id = scenario_id.strip()
            if scenario_id in scenario_id_set:
                packet = dict(packet)
                packet["scenario_id"] = scenario_id
                filtered_packets.append(packet)
                found_scenario_ids.add(scenario_id)
        missing_scenario_ids = sorted(scenario_id_set - found_scenario_ids)
        if missing_scenario_ids:
            raise ValueError(f"{packets_in} is missing requested scenarios: {missing_scenario_ids}")
        return filtered_packets

    kg = KgSnapshot(snapshot)
    return [_run_scenario(kg, scenario_id) for scenario_id in scenario_ids]


def _run_scenario(kg: KgSnapshot, scenario_id: str) -> JsonObject:
    plan = SCENARIO_PLANS[scenario_id]
    step_results = plan.run(kg)
    return EvidencePacketBuilder(
        scenario_id=plan.scenario_id,
        user_query=plan.user_query,
        expected_answer_shape=plan.expected_answer_shape,
    ).build(step_results)


async def _synthesize_answers(
    snapshot: str,
    packets: list[JsonObject],
    config: AnswerSynthesisConfig,
) -> JsonObject:
    synthesizer = ClaudeAnswerSynthesizer(config)
    answers = []
    for packet in packets:
        answer = await synthesizer.synthesize(packet)
        answer["user_query"] = packet.get("user_query")
        answer["expected_answer_shape"] = packet.get("expected_answer_shape")
        answer["evidence_item_count"] = len(packet.get("evidence_items", []))
        answer["retrieval_step_count"] = len(packet.get("retrieval_steps", []))
        answers.append(answer)

    return {
        "snapshot": str(Path(snapshot).expanduser()),
        "model": config.model,
        "scenario_count": len(answers),
        "answers": answers,
    }


def _write_json(path: Path, value: JsonObject) -> None:
    _write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, value: str) -> None:
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()
