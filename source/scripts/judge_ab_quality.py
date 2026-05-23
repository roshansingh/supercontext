from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from source.kg.integrations.llm import LightLlmClient
from source.scripts.compute_ab_deltas import load_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge blinded BetterContext A/B answer quality.")
    parser.add_argument("--judge-model", required=True, help="Model name used by the judge.")
    parser.add_argument("--deltas", required=True, help="Input deltas JSONL.")
    parser.add_argument("--out", required=True, help="Output judged deltas JSONL.")
    parser.add_argument("--seed", type=int, default=0, help="Presentation randomization seed.")
    args = parser.parse_args()

    rows = judge_rows(load_jsonl(Path(args.deltas)), judge_model=args.judge_model, seed=args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def judge_rows(
    rows: list[dict[str, Any]],
    *,
    judge_model: str,
    seed: int = 0,
    client_factory=LightLlmClient,
) -> list[dict[str, Any]]:
    judged = []
    client = client_factory(model=judge_model)
    for index, row in enumerate(rows):
        if row.get("quality_verdict") == "auto":
            judged.append(dict(row))
            continue
        updated = dict(row)
        updated["judge_model"] = judge_model
        updated["judge_prompt_seed"] = seed
        updated["judge_prompt_index"] = index
        prompt, label_to_arm = build_judge_prompt(row, rng=random.Random(seed + index))
        try:
            response = client.respond(prompt)
            parsed = parse_judge_response(response, label_to_arm=label_to_arm)
        except Exception as exc:
            updated["quality_verdict"] = "judge_error"
            updated["judge_error"] = str(exc)
            judged.append(updated)
            continue
        updated.update(parsed)
        updated["quality_verdict"] = "judged"
        judged.append(updated)
    return judged


def build_judge_prompt(row: dict[str, Any], *, rng: random.Random) -> tuple[str, dict[str, str]]:
    answers = [
        ("mcp_on", str(row.get("on", {}).get("answer") or "")),
        ("mcp_off", str(row.get("off", {}).get("answer") or "")),
    ]
    rng.shuffle(answers)
    label_to_arm = {"A": answers[0][0], "B": answers[1][0]}
    prompt = f"""Judge the two answers for correctness and evidence quality.

Task: {row.get("task_id")}
Phase: {row.get("phase")}

Answer A:
{answers[0][1]}

Answer B:
{answers[1][1]}

Return strict JSON with keys:
- winner: "A", "B", or "tie"
- confidence: number from 0 to 1
- reasoning: short reason focused on correctness first, then evidence quality
"""
    return prompt, label_to_arm


def parse_judge_response(response: str, *, label_to_arm: dict[str, str]) -> dict[str, Any]:
    response_json = _extract_json_object(response)
    try:
        payload = json.loads(response_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge response was not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("judge response must be a JSON object")
    winner = payload.get("winner")
    if winner not in {"A", "B", "tie"}:
        raise ValueError("judge response winner must be A, B, or tie")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
        raise ValueError("judge response confidence must be a number from 0 to 1")
    reasoning = payload.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("judge response reasoning must be a non-empty string")
    return {
        "judge_winner": "tie" if winner == "tie" else label_to_arm[winner],
        "judge_confidence": confidence,
        "judge_reasoning": reasoning.strip(),
    }


def _extract_json_object(response: str) -> str:
    stripped = response.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


if __name__ == "__main__":
    main()
