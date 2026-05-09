from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

from source.kg.core.models import JsonObject


DEFAULT_ANSWER_MODEL = "opus"
FAILURE_MODES = ("missing KG fact", "bad retrieval plan", "bad synthesis", "none", "other")
SCORE_VALUES = ("Pass", "Partial", "Fail")


@dataclass(frozen=True)
class AnswerSynthesisConfig:
    model: str = DEFAULT_ANSWER_MODEL
    max_turns: int | None = None
    load_timeout_ms: int = 180_000
    max_budget_usd: float = 0.25


class ClaudeAnswerSynthesizer:
    def __init__(self, config: AnswerSynthesisConfig | None = None) -> None:
        self.config = config or AnswerSynthesisConfig()

    async def synthesize(self, packet: JsonObject) -> JsonObject:
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is required. Install with `pip install claude-agent-sdk`."
            ) from exc

        stderr_lines: list[str] = []
        try:
            result_text = ""
            async for message in query(
                prompt=_prompt_for_packet(packet),
                options=ClaudeAgentOptions(
                    tools=None,
                    model=self.config.model,
                    max_turns=self.config.max_turns,
                    max_budget_usd=self.config.max_budget_usd,
                    allowed_tools=[],
                    disallowed_tools=[
                        "Agent",
                        "Bash",
                        "Edit",
                        "Glob",
                        "Grep",
                        "LS",
                        "Read",
                        "Task",
                        "TodoWrite",
                        "WebFetch",
                        "WebSearch",
                        "Write",
                    ],
                    permission_mode="dontAsk",
                    cli_path=which("claude"),
                    cwd=Path.cwd(),
                    extra_args={"bare": None},
                    load_timeout_ms=self.config.load_timeout_ms,
                    stderr=stderr_lines.append,
                    system_prompt=_system_prompt(),
                ),
            ):
                if isinstance(message, ResultMessage):
                    result_text = str(message.result)
        except Exception as exc:
            stderr_tail = "\n".join(stderr_lines[-20:]).strip()
            detail = f"\nClaude stderr tail:\n{stderr_tail}" if stderr_tail else ""
            raise RuntimeError(
                f"Claude Agent SDK answer synthesis failed for {packet.get('scenario_id')}: {exc}{detail}"
            ) from exc

        answer = _parse_json_result(result_text)
        answer["scenario_id"] = packet.get("scenario_id")
        answer["model"] = self.config.model
        _validate_answer(answer)
        return answer


def render_answers_markdown(result: JsonObject) -> str:
    lines = [
        "# LatticeAI Goldset Answer Synthesis",
        "",
        f"- Snapshot: `{result['snapshot']}`",
        f"- Model: `{result['model']}`",
        f"- Scenario count: {result['scenario_count']}",
        "",
        "## Summary",
        "",
        "| Scenario | Score | Failure Modes | Notes |",
        "|---|---|---|---|",
    ]
    for answer in result["answers"]:
        lines.append(
            "| {scenario} | {score} | {failure_modes} | {notes} |".format(
                scenario=answer["scenario_id"],
                score=answer["score"],
                failure_modes=", ".join(answer.get("failure_modes", [])),
                notes=_one_line(answer.get("score_reason", "")),
            )
        )

    for answer in result["answers"]:
        lines.extend(
            [
                "",
                f"## {answer['scenario_id']} - {answer['score']}",
                "",
                f"**Question:** {answer.get('user_query', '')}",
                "",
                "### Answer",
                "",
                answer["answer"].strip(),
                "",
                "### Caveats",
                "",
            ]
        )
        lines.extend(_bullet_lines(answer.get("caveats", [])))
        lines.extend(["", "### Unknown Because Missing Evidence", ""])
        lines.extend(_bullet_lines(answer.get("unknowns", [])))
        lines.extend(["", "### Score Notes", "", answer["score_reason"].strip()])

    return "\n".join(lines).rstrip() + "\n"


def _system_prompt() -> str:
    return (
        "You synthesize product-validation answers from a precomputed KG evidence packet. "
        "The KG is the only retrieval layer. Do not use tools, do not search, and do not infer facts "
        "that are not supported by the packet. Be concise and useful to real engineers, EMs, or "
        "security reviewers. Always cite evidence with repo/path/line coordinates when available."
    )


def _prompt_for_packet(packet: JsonObject) -> str:
    compact_packet = {
        "scenario_id": packet.get("scenario_id"),
        "user_query": packet.get("user_query"),
        "expected_answer_shape": packet.get("expected_answer_shape"),
        "retrieval_steps": packet.get("retrieval_steps", []),
        "evidence_items": [_compact_evidence_item(row) for row in packet.get("evidence_items", [])],
        "unknowns": packet.get("unknowns", []),
    }
    return f"""Create a grounded answer from this EvidencePacket.

Rules:
- Use only the packet. Do not search, read files, or rely on outside knowledge.
- Include citations inline using `[repo/path:Lstart-Lend]` when coordinates exist.
- If evidence is missing, say so under unknowns instead of guessing.
- Use only evidence that directly answers the user query or expected answer shape.
- Omit unrelated dependencies, package links, or "related context" even if present in the packet.
- Keep the answer concise but decision-useful.
- Score the answer against the expected answer shape as `Pass`, `Partial`, or `Fail`.
- Failure modes must be chosen from: {", ".join(FAILURE_MODES)}.
- Return JSON only with this shape:
{{
  "user_query": "...",
  "answer": "concise markdown answer with citations",
  "caveats": ["..."],
  "unknowns": ["..."],
  "score": "Pass|Partial|Fail",
  "score_reason": "...",
  "failure_modes": ["missing KG fact|bad retrieval plan|bad synthesis|none|other"]
}}

EvidencePacket:
{json.dumps(compact_packet, indent=2, sort_keys=True)}
"""


def _compact_evidence_item(row: JsonObject) -> JsonObject:
    return {
        "claim": row.get("claim"),
        "fact_type": row.get("fact_type"),
        "subject": row.get("subject"),
        "object": row.get("object"),
        "repo": row.get("repo"),
        "path": row.get("path"),
        "line_start": row.get("line_start"),
        "line_end": row.get("line_end"),
        "source_system": row.get("source_system"),
        "derivation_class": row.get("derivation_class"),
        "confidence": row.get("confidence"),
        "reconciliation_group": row.get("reconciliation_group"),
        "possible_match": row.get("possible_match"),
        "similarity": row.get("similarity"),
        "step": row.get("step"),
        "qualifier": row.get("qualifier", {}),
    }


def _parse_json_result(result_text: str) -> JsonObject:
    text = result_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude returned non-JSON answer synthesis output: {result_text[:500]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Claude answer synthesis output must be a JSON object")
    return value


def _validate_answer(answer: JsonObject) -> None:
    score = answer.get("score")
    if score not in SCORE_VALUES:
        raise RuntimeError(f"Invalid answer score: {score!r}")
    failure_modes = answer.get("failure_modes", [])
    if not isinstance(failure_modes, list) or not failure_modes:
        raise RuntimeError("Answer must include at least one failure mode")
    invalid_modes = [mode for mode in failure_modes if mode not in FAILURE_MODES]
    if invalid_modes:
        raise RuntimeError(f"Invalid failure modes: {invalid_modes}")
    for key in ("answer", "score_reason"):
        if not isinstance(answer.get(key), str) or not answer[key].strip():
            raise RuntimeError(f"Answer field {key!r} must be a non-empty string")


def _bullet_lines(values: list[Any]) -> list[str]:
    if not values:
        return ["- None."]
    return [f"- {str(value).strip()}" for value in values]


def _one_line(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
