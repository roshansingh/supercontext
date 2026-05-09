from __future__ import annotations

from dataclasses import dataclass

from source.kg.models import JsonObject


@dataclass(frozen=True)
class EvidencePacketBuilder:
    scenario_id: str
    user_query: str
    expected_answer_shape: str

    def build(self, step_results: list[JsonObject]) -> JsonObject:
        evidence_items = []
        unknowns = []
        for step_result in step_results:
            result = step_result["result"]
            if result.get("status") in {"not_found", "empty"}:
                unknowns.append(
                    {
                        "step": step_result["step"],
                        "command": step_result["command"],
                        "reason": f"No facts returned for {step_result['purpose']}",
                    }
                )
                continue
            evidence_items.extend(self._items_from_result(step_result))

        return {
            "scenario_id": self.scenario_id,
            "user_query": self.user_query,
            "expected_answer_shape": self.expected_answer_shape,
            "retrieval_steps": [
                {
                    "step": row["step"],
                    "command": row["command"],
                    "args": row["args"],
                    "purpose": row["purpose"],
                    "status": row["result"].get("status"),
                }
                for row in step_results
            ],
            "evidence_items": _dedupe_items(evidence_items),
            "unknowns": unknowns,
        }

    def _items_from_result(self, step_result: JsonObject) -> list[JsonObject]:
        result = step_result["result"]
        rows = []
        for key in ("references", "endpoints", "event_channels", "mappings", "dependencies", "links"):
            for row in result.get(key, []):
                rows.extend(self._items_from_fact_row(step_result, row))
        for section in ("matched", "left_only", "right_only", "possible_matches"):
            rows.extend(self._items_from_reconciliation_section(step_result, section, result.get(section, [])))
        return rows

    def _items_from_reconciliation_section(
        self,
        step_result: JsonObject,
        section: str,
        rows: list[JsonObject],
    ) -> list[JsonObject]:
        items = []
        for row in rows:
            if section == "matched":
                for fact_row in row.get("left", []) + row.get("right", []):
                    items.extend(self._items_from_fact_row(step_result, {**fact_row, "reconciliation_group": section}))
            elif section in {"left_only", "right_only"}:
                for fact_row in row.get("rows", []):
                    items.extend(self._items_from_fact_row(step_result, {**fact_row, "reconciliation_group": section}))
            elif section == "possible_matches":
                for fact_row in row.get("left", []) + row.get("right", []):
                    items.extend(
                        self._items_from_fact_row(
                            step_result,
                            {
                                **fact_row,
                                "reconciliation_group": section,
                                "similarity": row.get("similarity"),
                                "possible_match": {
                                    "left_key": row.get("left_key"),
                                    "right_key": row.get("right_key"),
                                },
                            },
                        )
                    )
        return items

    def _items_from_fact_row(self, step_result: JsonObject, row: JsonObject) -> list[JsonObject]:
        evidence_rows = row.get("evidence", [])
        if not evidence_rows:
            return [
                {
                    "claim": _claim_for_row(row),
                    "fact_id": row.get("fact_id"),
                    "fact_type": row.get("predicate") or row.get("fact_type"),
                    "subject": row.get("subject"),
                    "object": row.get("object"),
                    "qualifier": row.get("qualifier", {}),
                    "reconciliation_group": row.get("reconciliation_group"),
                    "possible_match": row.get("possible_match"),
                    "similarity": row.get("similarity"),
                    "step": step_result["step"],
                    "source_system": None,
                    "derivation_class": None,
                    "confidence": None,
                    "repo": None,
                    "commit_sha": None,
                    "path": None,
                    "line_start": None,
                    "line_end": None,
                }
            ]

        return [
            {
                "claim": _claim_for_row(row),
                "fact_id": row.get("fact_id"),
                "fact_type": row.get("predicate") or row.get("fact_type"),
                "subject": row.get("subject"),
                "object": row.get("object"),
                "qualifier": row.get("qualifier", {}),
                "reconciliation_group": row.get("reconciliation_group"),
                "possible_match": row.get("possible_match"),
                "similarity": row.get("similarity"),
                "step": step_result["step"],
                "source_system": evidence.get("source_system"),
                "derivation_class": evidence.get("derivation_class"),
                "confidence": evidence.get("confidence"),
                **_bytes_coordinates(evidence),
            }
            for evidence in evidence_rows
        ]


def _claim_for_row(row: JsonObject) -> str:
    predicate = row.get("predicate") or row.get("fact_type")
    subject = row.get("subject")
    object_ = row.get("object")
    group = row.get("reconciliation_group")
    prefix = f"{group}: " if group else ""
    if predicate == "REFERENCES_DOMAIN":
        return f"{prefix}{subject} references domain {object_}."
    if predicate == "ROUTES_DOMAIN_TO_DEPLOY":
        return f"{prefix}{subject} routes to deploy target {object_}."
    if predicate == "EXPOSES_ENDPOINT":
        return f"{prefix}{subject} exposes endpoint {object_}."
    if predicate == "CALLS_ENDPOINT":
        return f"{prefix}{subject} calls endpoint {object_}."
    if predicate == "DOCUMENTS_ENDPOINT":
        return f"{prefix}{subject} documents endpoint {object_}."
    if predicate == "REFERENCES_EVENT_CHANNEL":
        return f"{prefix}{subject} references event channel {object_}."
    if predicate == "CONSUMES_EVENT":
        return f"{prefix}{subject} consumes event channel {object_}."
    if predicate == "RESOLVES_TO_REPO":
        return f"{prefix}{subject} resolves to repo {object_}."
    if predicate == "RESOLVES_TO_SERVICE":
        return f"{prefix}{subject} resolves to service {object_}."
    return f"{prefix}{subject} {predicate} {object_}."


def _bytes_coordinates(evidence: JsonObject) -> JsonObject:
    bytes_ref = evidence.get("bytes_ref") or {}
    return {
        "repo": bytes_ref.get("repo"),
        "commit_sha": bytes_ref.get("commit_sha"),
        "path": bytes_ref.get("path"),
        "line_start": bytes_ref.get("line_start"),
        "line_end": bytes_ref.get("line_end"),
    }


def _dedupe_items(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[object, ...]] = set()
    deduped = []
    for item in items:
        key = (
            item.get("claim"),
            item.get("repo"),
            item.get("path"),
            item.get("line_start"),
            item.get("line_end"),
            item.get("source_system"),
            item.get("reconciliation_group"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(
        deduped,
        key=lambda row: (
            str(row.get("repo") or ""),
            str(row.get("path") or ""),
            int(row.get("line_start") or 0),
            str(row.get("claim") or ""),
        ),
    )
