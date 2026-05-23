from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import JsonObject
from source.kg.product.claude_tool_policy import (
    DEFAULT_CLAUDE_PERMISSION_MODE,
    DISALLOWED_CLAUDE_TOOLS,
    resolve_claude_cli_path,
)
from source.kg.product.formatting import compact_evidence_item
from source.kg.product.json_result import parse_json_object_result


DEFAULT_INTERACTIVE_MODEL = "opus"
DEFAULT_INTERACTIVE_MAX_BUDGET_USD = 1.0


@dataclass(frozen=True)
class AgentRuntimeConfig:
    model: str = DEFAULT_INTERACTIVE_MODEL
    max_turns: int | None = None
    load_timeout_ms: int = 180_000
    max_budget_usd: float = DEFAULT_INTERACTIVE_MAX_BUDGET_USD
    permission_mode: str = DEFAULT_CLAUDE_PERMISSION_MODE
    claude_cli_path: str | None = None


class ClaudeInteractiveAgentSession:
    """Conversation-scoped Agent SDK runtime for interactive KG questions."""

    def __init__(self, config: AgentRuntimeConfig | None = None) -> None:
        self.config = config or AgentRuntimeConfig()
        self._client = None
        self._result_message_type = None

    async def __aenter__(self) -> "ClaudeInteractiveAgentSession":
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is required. Install with `pip install claude-agent-sdk`."
            ) from exc

        self._result_message_type = ResultMessage
        options = ClaudeAgentOptions(
            tools=None,
            model=self.config.model,
            max_turns=self.config.max_turns,
            max_budget_usd=self.config.max_budget_usd,
            allowed_tools=[],
            disallowed_tools=list(DISALLOWED_CLAUDE_TOOLS),
            permission_mode=self.config.permission_mode,
            cli_path=resolve_claude_cli_path(self.config.claude_cli_path),
            cwd=Path.cwd(),
            extra_args={"bare": None},
            load_timeout_ms=self.config.load_timeout_ms,
            system_prompt=_system_prompt(),
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)

    async def plan_query(self, user_query: str, kg_state: JsonObject) -> JsonObject:
        return parse_json_object_result(
            await self._send(_planning_prompt(user_query, kg_state)),
            "interactive query planning",
        )

    async def synthesize_answer(self, packet: JsonObject, plan: JsonObject, kg_state: JsonObject) -> JsonObject:
        answer = parse_json_object_result(
            await self._send(_answer_prompt(packet, plan, kg_state)),
            "interactive answer synthesis",
        )
        _validate_answer(answer)
        answer["user_query"] = packet.get("user_query")
        return answer

    async def _send(self, prompt: str) -> str:
        if self._client is None or self._result_message_type is None:
            raise RuntimeError("ClaudeInteractiveAgentSession must be used as an async context manager")
        await self._client.query(prompt)
        result_text = ""
        async for message in self._client.receive_response():
            if isinstance(message, self._result_message_type):
                result_text = str(message.result)
        return result_text


def _system_prompt() -> str:
    return (
        "You are the SuperContext interactive KG agent runtime. The KG retrieval layer is authoritative. "
        "You do not use tools, do not search, do not read files, and do not invent facts. First produce a "
        "small retrieval plan from the user's natural-language query. After the host executes the plan, "
        "synthesize only from the returned EvidencePacket."
    )


def _planning_prompt(user_query: str, kg_state: JsonObject) -> str:
    return f"""Plan KG retrieval for this natural-language question.

Allowed anchor kinds:
- DeployTarget: deploy target filenames, entrypoints, process names, container/workload names
- Domain: DNS names or hostnames
- Endpoint: HTTP paths such as /api/orders
- EventChannel: queue/topic/event channel names or ARNs
- Package: external packages/import roots such as sklearn, pandas, express
- Repo: repository names
- Symbol: function/class/method names

Rules:
- Return JSON only.
- Use at most 8 anchors.
- Prefer clarification over guessing when the query is too vague.
- Refuse if the query is outside code/KG evidence scope.
- Do not include private corpus assumptions.

JSON shape:
{{
  "anchors": [{{"kind": "Package|Symbol|Domain|Endpoint|EventChannel|Repo|DeployTarget", "value": "..."}}],
  "answer_intent": "short description of what the user wants",
  "clarification": null,
  "refusal_reason": null,
  "debug_notes": ["..."]
}}

KG state:
{json.dumps(_compact_kg_state(kg_state), indent=2, sort_keys=True)}

User question:
{user_query}
"""


def _answer_prompt(packet: JsonObject, plan: JsonObject, kg_state: JsonObject) -> str:
    compact_packet = {
        "user_query": packet.get("user_query"),
        "expected_answer_shape": packet.get("expected_answer_shape"),
        "retrieval_steps": packet.get("retrieval_steps", []),
        "evidence_items": [compact_evidence_item(row) for row in packet.get("evidence_items", [])[:80]],
        "unknowns": packet.get("unknowns", []),
    }
    return f"""Synthesize an interactive answer from this KG EvidencePacket.

Rules:
- Use only this packet and the retrieval plan. Do not use outside knowledge.
- Cite file/line coordinates inline when present, using [repo/path:Lstart-Lend].
- If evidence is missing, say so under unknowns instead of guessing.
- Keep the answer concise and useful to an engineer.
- Return JSON only with this shape:
{{
  "answer": "markdown answer with citations",
  "caveats": ["..."],
  "unknowns": ["..."],
  "citations": [{{"repo": "...", "path": "...", "line_start": 1, "line_end": 1}}],
  "debug_notes": ["..."]
}}

Retrieval plan:
{json.dumps(plan, indent=2, sort_keys=True)}

KG state:
{json.dumps(_compact_kg_state(kg_state), indent=2, sort_keys=True)}

EvidencePacket:
{json.dumps(compact_packet, indent=2, sort_keys=True)}
"""


def _compact_kg_state(kg_state: JsonObject) -> JsonObject:
    coverage = kg_state.get("coverage")
    coverage_count = len(coverage) if isinstance(coverage, list) else kg_state.get("coverage_count")
    return {
        "entity_counts": kg_state.get("entity_counts") or kg_state.get("entity_kinds") or {},
        "predicate_counts": kg_state.get("predicate_counts") or kg_state.get("predicates") or {},
        "coverage_count": coverage_count,
    }


def _validate_answer(answer: JsonObject) -> None:
    if not isinstance(answer.get("answer"), str) or not str(answer.get("answer", "")).strip():
        raise ValueError("Interactive answer requires a non-empty answer string")
    for field in ("caveats", "unknowns", "debug_notes"):
        value = answer.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"Interactive answer {field} must be a list")
    citations = answer.get("citations", [])
    if not isinstance(citations, list) or any(not isinstance(row, dict) for row in citations):
        raise ValueError("Interactive answer citations must be a list of objects")
