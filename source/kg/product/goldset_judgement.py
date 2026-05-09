from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

from source.kg.core.models import JsonObject
from source.kg.product.answer_synthesis import DEFAULT_ANSWER_MODEL, _compact_evidence_item, _one_line


JUDGEMENT_SCORES = ("Pass", "Partial", "Fail")
EVIDENCE_COMPLETENESS = ("complete", "partial", "missing")
FAILURE_OWNERS = ("missing KG fact", "bad retrieval plan", "bad synthesis", "ground truth issue", "none")


@dataclass(frozen=True)
class GoldsetScenario:
    scenario_id: str
    user_query: str
    expected_answer_shape: str
    ground_truth_answer: str


@dataclass(frozen=True)
class GoldsetJudgementConfig:
    model: str = DEFAULT_ANSWER_MODEL
    max_budget_usd: float = 0.25
    load_timeout_ms: int = 180_000


class ClaudeGoldsetJudge:
    def __init__(self, config: GoldsetJudgementConfig | None = None) -> None:
        self.config = config or GoldsetJudgementConfig()

    async def judge(self, scenario: GoldsetScenario, packet: JsonObject, answer: JsonObject) -> JsonObject:
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
                prompt=_prompt_for_judgement(scenario, packet, answer),
                options=ClaudeAgentOptions(
                    tools=None,
                    model=self.config.model,
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
                f"Claude goldset judgement failed for {scenario.scenario_id}: {exc}{detail}"
            ) from exc

        judgement = _parse_json_result(result_text)
        judgement["scenario_id"] = scenario.scenario_id
        judgement["model"] = self.config.model
        _validate_judgement(judgement)
        return judgement


def load_goldset_scenarios(path: str | Path, scenario_ids: set[str]) -> dict[str, GoldsetScenario]:
    rows = _parse_markdown_table(Path(path).expanduser())
    scenarios: dict[str, GoldsetScenario] = {}
    for row in rows:
        scenario_id = row.get("ID", "")
        if scenario_id not in scenario_ids:
            continue
        ground_truth = row.get("Ground Truth Answer", "")
        if not ground_truth or ground_truth == "Not in initial goldset.":
            continue
        scenarios[scenario_id] = GoldsetScenario(
            scenario_id=scenario_id,
            user_query=row.get("User Query", ""),
            expected_answer_shape=row.get("Expected Answer Shape", ""),
            ground_truth_answer=ground_truth,
        )
    return scenarios


def render_judgements_markdown(result: JsonObject) -> str:
    lines = [
        "# LatticeAI Goldset Judgement",
        "",
        f"- Query set: `{result['query_set']}`",
        f"- Packets: `{result['packets']}`",
        f"- Answers: `{result['answers']}`",
        f"- Model: `{result['model']}`",
        f"- Scenario count: {result['scenario_count']}",
        f"- Skipped missing ground truth: {', '.join(result.get('skipped_missing_ground_truth', [])) or 'None'}",
        "",
        "## Summary",
        "",
        "| Scenario | Evidence | Answer | Failure Owner | Notes |",
        "|---|---|---|---|---|",
    ]
    for judgement in result["judgements"]:
        lines.append(
            "| {scenario} | {evidence} | {answer} | {owner} | {notes} |".format(
                scenario=judgement["scenario_id"],
                evidence=judgement["evidence_completeness"],
                answer=judgement["answer_score"],
                owner=", ".join(judgement.get("failure_owners", [])),
                notes=_one_line(judgement.get("summary", "")),
            )
        )

    for judgement in result["judgements"]:
        lines.extend(
            [
                "",
                f"## {judgement['scenario_id']} - {judgement['answer_score']}",
                "",
                f"**Evidence completeness:** {judgement['evidence_completeness']}",
                "",
                f"**Failure owner:** {', '.join(judgement.get('failure_owners', []))}",
                "",
                "### Summary",
                "",
                judgement["summary"].strip(),
                "",
                "### Ground Truth Coverage",
                "",
            ]
        )
        lines.extend(_bullet_lines(judgement.get("ground_truth_coverage", [])))
        lines.extend(["", "### Missing Or Weak Evidence", ""])
        lines.extend(_bullet_lines(judgement.get("missing_or_weak_evidence", [])))
        lines.extend(["", "### Answer Issues", ""])
        lines.extend(_bullet_lines(judgement.get("answer_issues", [])))
        lines.extend(["", "### Recommended Next Action", "", judgement["recommended_next_action"].strip()])

    return "\n".join(lines).rstrip() + "\n"


def _system_prompt() -> str:
    return (
        "You are an independent product-validation judge. You compare ground truth, a KG evidence packet, "
        "and a synthesized answer. Do not use tools, do not search, and do not rely on outside knowledge. "
        "Your job is to determine whether the KG evidence was sufficient and whether the answer matched "
        "the independent ground truth."
    )


def _prompt_for_judgement(scenario: GoldsetScenario, packet: JsonObject, answer: JsonObject) -> str:
    compact_packet = {
        "scenario_id": packet.get("scenario_id"),
        "user_query": packet.get("user_query"),
        "expected_answer_shape": packet.get("expected_answer_shape"),
        "retrieval_steps": packet.get("retrieval_steps", []),
        "evidence_items": [_compact_evidence_item(row) for row in packet.get("evidence_items", [])],
        "unknowns": packet.get("unknowns", []),
    }
    compact_answer = {
        "answer": answer.get("answer"),
        "caveats": answer.get("caveats", []),
        "unknowns": answer.get("unknowns", []),
        "self_score": answer.get("score"),
        "self_failure_modes": answer.get("failure_modes", []),
        "self_score_reason": answer.get("score_reason"),
    }
    return f"""Judge this goldset result.

Rules:
- Use only these inputs. Do not search or assume facts outside them.
- Evidence completeness asks whether the EvidencePacket contains enough facts to reconstruct the Ground Truth Answer.
- Answer score asks whether the Generated Answer correctly covers the Ground Truth Answer.
- If ground truth facts are absent from the EvidencePacket, mark evidence as `partial` or `missing`.
- If evidence is present but answer omits or distorts it, mark `bad synthesis`.
- If evidence may exist in the KG but the packet did not retrieve it, use `bad retrieval plan`; if you cannot know, say so in notes.
- If the independent ground truth appears incomplete or contradicts the packet, use `ground truth issue`.
- Do not trust the generated answer's self-score.
- Return JSON only with this shape:
{{
  "evidence_completeness": "complete|partial|missing",
  "answer_score": "Pass|Partial|Fail",
  "failure_owners": ["missing KG fact|bad retrieval plan|bad synthesis|ground truth issue|none"],
  "summary": "...",
  "ground_truth_coverage": ["..."],
  "missing_or_weak_evidence": ["..."],
  "answer_issues": ["..."],
  "recommended_next_action": "..."
}}

Scenario:
{json.dumps({
    "scenario_id": scenario.scenario_id,
    "user_query": scenario.user_query,
    "expected_answer_shape": scenario.expected_answer_shape,
    "ground_truth_answer": scenario.ground_truth_answer,
}, indent=2, sort_keys=True)}

EvidencePacket:
{json.dumps(compact_packet, indent=2, sort_keys=True)}

Generated Answer:
{json.dumps(compact_answer, indent=2, sort_keys=True)}
"""


def _parse_json_result(result_text: str) -> JsonObject:
    text = result_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude returned non-JSON judgement output: {result_text[:500]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Claude judgement output must be a JSON object")
    return value


def _validate_judgement(judgement: JsonObject) -> None:
    if judgement.get("evidence_completeness") not in EVIDENCE_COMPLETENESS:
        raise RuntimeError(f"Invalid evidence completeness: {judgement.get('evidence_completeness')!r}")
    if judgement.get("answer_score") not in JUDGEMENT_SCORES:
        raise RuntimeError(f"Invalid answer score: {judgement.get('answer_score')!r}")
    failure_owners = judgement.get("failure_owners", [])
    if not isinstance(failure_owners, list) or not failure_owners:
        raise RuntimeError("Judgement must include at least one failure owner")
    invalid = [owner for owner in failure_owners if owner not in FAILURE_OWNERS]
    if invalid:
        raise RuntimeError(f"Invalid failure owners: {invalid}")
    for key in ("summary", "recommended_next_action"):
        if not isinstance(judgement.get(key), str) or not judgement[key].strip():
            raise RuntimeError(f"Judgement field {key!r} must be a non-empty string")


def _parse_markdown_table(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_markdown_row(stripped)
        if not cells:
            continue
        if cells[0] == "ID":
            header = cells
            continue
        if header is None or not cells[0].startswith("Q"):
            continue
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        rows.append(dict(zip(header, cells, strict=False)))
    return rows


def _split_markdown_row(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if cells and all(set(cell) <= {"-", ":"} for cell in cells):
        return []
    return cells


def _bullet_lines(values: list[Any]) -> list[str]:
    if not values:
        return ["- None."]
    return [f"- {str(value).strip()}" for value in values]
