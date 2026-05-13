from __future__ import annotations

from source.kg.core.models import JsonObject
from source.kg.product.evidence_packet import EvidencePacketBuilder
from source.kg.product.retrieval_planner import RetrievalStep, plan_retrieval_steps_from_mappings
from source.kg.query.snapshot import KgSnapshot


def validate_interactive_plan(plan: JsonObject, *, limit: int = 25) -> JsonObject:
    if not isinstance(plan, dict):
        raise ValueError("Interactive plan must be a JSON object")
    anchors = plan.get("anchors")
    clarification = _optional_string(plan.get("clarification"), "clarification")
    refusal_reason = _optional_string(plan.get("refusal_reason"), "refusal_reason")
    if anchors is None:
        anchors = []
    if not isinstance(anchors, list):
        raise ValueError("Interactive plan anchors must be a list")
    if len(anchors) > 8:
        raise ValueError("Interactive plan can include at most 8 anchors")
    if not anchors and not clarification and not refusal_reason:
        raise ValueError("Interactive plan must include anchors, clarification, or refusal_reason")

    steps = plan_retrieval_steps_from_mappings(anchors, limit=limit) if anchors else ()
    return {
        "anchors": [dict(anchor) for anchor in anchors],
        "answer_intent": _optional_string(plan.get("answer_intent"), "answer_intent") or "",
        "clarification": clarification,
        "refusal_reason": refusal_reason,
        "debug_notes": _string_list(plan.get("debug_notes"), "debug_notes"),
        "retrieval_steps": [_step_to_json(step) for step in steps],
    }


def execute_interactive_plan(
    kg: KgSnapshot,
    *,
    user_query: str,
    plan: JsonObject,
    limit: int = 25,
    ground_truth: JsonObject | None = None,
) -> JsonObject:
    validated_plan = validate_interactive_plan(plan, limit=limit)
    steps = plan_retrieval_steps_from_mappings(validated_plan["anchors"], limit=limit)
    kg_state = kg.summary()
    step_results = [_step_result(kg, step) for step in steps]
    packet = EvidencePacketBuilder(
        scenario_id="interactive",
        user_query=user_query,
        expected_answer_shape=validated_plan["answer_intent"] or "Answer the user's interactive KG question.",
    ).build(step_results)
    return {
        "plan": validated_plan,
        "retrieval_steps": validated_plan["retrieval_steps"],
        "step_results": step_results,
        "packet": packet,
        "kg_state": kg_state,
        "ground_truth": ground_truth or {},
    }


def _step_result(kg: KgSnapshot, step: RetrievalStep) -> JsonObject:
    raw_result = step.run(kg)
    return {
        "step": step.name,
        "command": step.command,
        "args": dict(step.args),
        "purpose": step.purpose,
        "result": _normalize_result(step.command, raw_result),
    }


def _normalize_result(command: str, raw_result: JsonObject | list[JsonObject]) -> JsonObject:
    if isinstance(raw_result, dict):
        return raw_result
    if not isinstance(raw_result, list):
        raise ValueError(f"Retrieval command {command} returned unsupported result type")
    return {
        "status": "found" if raw_result else "empty",
        "returned_count": len(raw_result),
        _list_result_key(command): raw_result,
    }


def _list_result_key(command: str) -> str:
    if command == "modules_importing":
        return "references"
    if command == "repo_dependencies":
        return "dependencies"
    return "references"


def _step_to_json(step: RetrievalStep) -> JsonObject:
    return {
        "step": step.name,
        "command": step.command,
        "args": dict(step.args),
        "purpose": step.purpose,
    }


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Interactive plan {field_name} must be a string or null")
    stripped = value.strip()
    return stripped or None


def _string_list(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Interactive plan {field_name} must be a list")
    strings = []
    for index, row in enumerate(value):
        if not isinstance(row, str):
            raise ValueError(f"Interactive plan {field_name}[{index}] must be a string")
        stripped = row.strip()
        if stripped:
            strings.append(stripped)
    return strings
