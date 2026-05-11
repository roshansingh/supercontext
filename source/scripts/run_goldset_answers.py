from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from source.kg.core.models import JsonObject
from source.kg.product import (
    AnswerSynthesisConfig,
    ClaudeAnswerSynthesizer,
)
from source.kg.product.answer_synthesis import DEFAULT_ANSWER_MAX_BUDGET_USD, DEFAULT_ANSWER_MODEL, render_answers_markdown
from source.kg.product.artifact_consistency import packet_fingerprint
from source.kg.product.claude_tool_policy import DEFAULT_CLAUDE_PERMISSION_MODE
from source.kg.product.validation import normalize_unique_strings


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize product-validation answers from KG evidence packets.")
    parser.add_argument(
        "--snapshot",
        default="packet-input",
        help="Raw snapshot label to include in output metadata. Packet generation now lives under examples/private-goldset/.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario ID to run; repeatable. Defaults to all packets in --packets-in.",
    )
    parser.add_argument("--packets-in", required=True, help="Existing EvidencePacket JSON file")
    parser.add_argument("--packets-out", help="Optional path to write a wrapper object containing filtered packets")
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
        default=DEFAULT_ANSWER_MAX_BUDGET_USD,
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

    scenario_ids = normalize_unique_strings(tuple(args.scenario), "--scenario") if args.scenario else None
    packets = _load_packets(scenario_ids, args.packets_in)
    if args.packets_out:
        _write_json(
            Path(args.packets_out),
            {"snapshot": args.snapshot, "scenario_count": len(packets), "packets": packets},
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


def _load_packets(scenario_ids: tuple[str, ...] | None, packets_in: str) -> list[JsonObject]:
    data = json.loads(Path(packets_in).expanduser().read_text(encoding="utf-8"))
    packets = data.get("packets") if isinstance(data, dict) else data
    if not isinstance(packets, list):
        raise ValueError(f"{packets_in} must be a list or an object with a 'packets' list")
    scenario_id_set = set(scenario_ids or ())
    filtered_packets = []
    found_scenario_ids = set()
    for index, packet in enumerate(packets):
        if not isinstance(packet, dict):
            raise ValueError(f"{packets_in} packets[{index}] must be an object")
        scenario_id = packet.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError(f"{packets_in} packets[{index}] must include a non-empty scenario_id")
        scenario_id = scenario_id.strip()
        if scenario_ids is None or scenario_id in scenario_id_set:
            if scenario_id in found_scenario_ids:
                raise ValueError(f"{packets_in} packets[{index}] duplicates scenario_id {scenario_id!r}")
            _validate_packet_list_fields(packet, packets_in, index)
            packet = dict(packet)
            packet["scenario_id"] = scenario_id
            filtered_packets.append(packet)
            found_scenario_ids.add(scenario_id)
    if scenario_ids is not None:
        missing_scenario_ids = sorted(scenario_id_set - found_scenario_ids)
        if missing_scenario_ids:
            raise ValueError(f"{packets_in} is missing requested scenarios: {missing_scenario_ids}")
    return filtered_packets


def _load_or_build_packets(
    _snapshot: str,
    scenario_ids: tuple[str, ...] | None,
    packets_in: str | None,
) -> list[JsonObject]:
    # Deprecated compatibility guard for callers that used the old KG-to-packet path.
    if not packets_in:
        raise ValueError(
            "run_goldset_answers now requires --packets-in; private KG-to-packet scenario generation lives under "
            "examples/private-goldset/run_scenario.py"
        )
    return _load_packets(scenario_ids, packets_in)


def _validate_packet_list_fields(packet: JsonObject, packets_in: str, index: int) -> None:
    for field in ("evidence_items", "retrieval_steps", "unknowns"):
        if field in packet and not isinstance(packet[field], list):
            raise ValueError(f"{packets_in} packets[{index}].{field} must be a list")


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
        answer["packet_fingerprint"] = packet_fingerprint(packet)
        answers.append(answer)

    return {
        "snapshot": snapshot,
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
