from __future__ import annotations

from collections import deque

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


FRAMEWORK_PREDICATES = {
    "DECLARES_FIELD",
    "RELATES_TO_MODEL",
    "SERIALIZES_MODEL",
    "HANDLES_MODEL",
    "TASK_USES_MODEL",
}


def framework_impact_packet(
    kg: KgSnapshot,
    *,
    repo: str,
    changed_symbols: list[JsonObject],
    limit: int,
) -> JsonObject:
    if not _normalize_repo(repo):
        return {
            "status": "missing_repo",
            "summary": {
                "changed_framework_model_count": 0,
                "model_field_count": 0,
                "model_relation_count": 0,
                "serializer_count": 0,
                "view_count": 0,
                "task_count": 0,
                "relationship_path_count": 0,
                "section_limit": limit,
            },
            "changed_models": [],
            "model_fields": [],
            "model_relations": [],
            "serializers": [],
            "views": [],
            "tasks": [],
            "relationship_paths": [],
            "assembly_contract": _ASSEMBLY_CONTRACT,
        }
    changed_symbol_ids = {
        str(row["symbol_id"]) for row in changed_symbols if isinstance(row.get("symbol_id"), str) and row["symbol_id"]
    }
    framework_rows = _framework_rows(kg, repo=repo)
    impacted_model_ids = _impacted_model_ids(framework_rows, changed_symbols, changed_symbol_ids)

    model_fields = [
        row for row in framework_rows if row["predicate"] == "DECLARES_FIELD" and row["subject"]["entity_id"] in impacted_model_ids
    ]
    relation_rows = [
        row
        for row in framework_rows
        if row["predicate"] == "RELATES_TO_MODEL"
        and (
            row["object"]["entity_id"] in impacted_model_ids
            or _field_owner_id(row["subject"]["entity_id"], model_fields) in impacted_model_ids
        )
    ]
    serializer_rows = [
        row for row in framework_rows if row["predicate"] == "SERIALIZES_MODEL" and row["object"]["entity_id"] in impacted_model_ids
    ]
    view_rows = [
        row for row in framework_rows if row["predicate"] == "HANDLES_MODEL" and row["object"]["entity_id"] in impacted_model_ids
    ]
    task_rows = [
        row for row in framework_rows if row["predicate"] == "TASK_USES_MODEL" and row["object"]["entity_id"] in impacted_model_ids
    ]
    relationship_paths = _relationship_paths(framework_rows, impacted_model_ids, limit=limit)

    return {
        "status": "found" if impacted_model_ids else "empty",
        "summary": {
            "changed_framework_model_count": len(impacted_model_ids),
            "model_field_count": len(model_fields),
            "model_relation_count": len(relation_rows),
            "serializer_count": len(serializer_rows),
            "view_count": len(view_rows),
            "task_count": len(task_rows),
            "relationship_path_count": len(relationship_paths),
            "section_limit": limit,
        },
        "changed_models": _model_rows(kg, impacted_model_ids)[:limit],
        "model_fields": model_fields[:limit],
        "model_relations": relation_rows[:limit],
        "serializers": serializer_rows[:limit],
        "views": view_rows[:limit],
        "tasks": task_rows[:limit],
        "relationship_paths": relationship_paths[:limit],
        "assembly_contract": _ASSEMBLY_CONTRACT,
    }


def _framework_rows(kg: KgSnapshot, *, repo: str) -> list[JsonObject]:
    rows = []
    repo_key = _normalize_repo(repo)
    for fact in kg.support_facts:
        if fact.get("predicate") not in FRAMEWORK_PREDICATES:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if _entity_repo(subject) != repo_key and _entity_repo(object_) != repo_key:
            continue
        rows.append(
            {
                "fact_id": fact.get("fact_id"),
                "predicate": fact.get("predicate"),
                "subject": _entity_row(subject),
                "object": _entity_row(object_),
                "qualifier": fact.get("qualifier", {}),
                "evidence": kg.evidence_by_target.get(fact.get("fact_id"), []),
            }
        )
    return rows


def _impacted_model_ids(rows: list[JsonObject], changed_symbols: list[JsonObject], changed_symbol_ids: set[str]) -> set[str]:
    impacted = set()
    field_to_model = {
        row["object"]["entity_id"]: row["subject"]["entity_id"]
        for row in rows
        if row["predicate"] == "DECLARES_FIELD"
    }
    model_ids = set(field_to_model.values())
    for row in rows:
        if row["predicate"] in {"RELATES_TO_MODEL", "SERIALIZES_MODEL", "HANDLES_MODEL", "TASK_USES_MODEL"}:
            model_ids.add(row["object"]["entity_id"])
    for symbol_id in changed_symbol_ids:
        if symbol_id in model_ids:
            impacted.add(symbol_id)
        if symbol_id in field_to_model:
            impacted.add(field_to_model[symbol_id])
    for row in rows:
        if row["predicate"] in {"RELATES_TO_MODEL", "SERIALIZES_MODEL", "HANDLES_MODEL", "TASK_USES_MODEL"}:
            if _changed_symbol_matches_entity(row["object"], changed_symbols, changed_symbol_ids):
                impacted.add(row["object"]["entity_id"])
        if row["predicate"] in {"SERIALIZES_MODEL", "HANDLES_MODEL", "TASK_USES_MODEL"} and _changed_symbol_matches_entity(
            row["subject"], changed_symbols, changed_symbol_ids
        ):
            impacted.add(row["object"]["entity_id"])
    return impacted


def _changed_symbol_matches_entity(
    entity: JsonObject,
    changed_symbols: list[JsonObject],
    changed_symbol_ids: set[str],
) -> bool:
    if entity["entity_id"] in changed_symbol_ids:
        return True
    entity_repo = _normalize_repo(entity.get("repo"))
    entity_module = entity.get("module")
    entity_qualname = entity.get("qualname")
    if not isinstance(entity_module, str) or not isinstance(entity_qualname, str):
        return False
    for symbol in changed_symbols:
        if _normalize_repo(symbol.get("repo")) != entity_repo:
            continue
        if symbol.get("module") != entity_module:
            continue
        changed_qualname = symbol.get("qualname")
        if not isinstance(changed_qualname, str):
            continue
        if changed_qualname.startswith(f"{entity_qualname}."):
            return True
    return False


def _field_owner_id(field_id: object, field_rows: list[JsonObject]) -> object | None:
    for row in field_rows:
        if row["object"].get("entity_id") == field_id:
            return row["subject"].get("entity_id")
    return None


def _model_rows(kg: KgSnapshot, model_ids: set[str]) -> list[JsonObject]:
    return [_entity_row(entity) for entity_id in sorted(model_ids) if (entity := kg.entities_by_id.get(entity_id))]


def _relationship_paths(rows: list[JsonObject], roots: set[str], *, limit: int) -> list[JsonObject]:
    field_to_model = {
        row["subject"]["entity_id"]: row["object"]["entity_id"]
        for row in rows
        if row["predicate"] == "RELATES_TO_MODEL"
    }
    # Django fields are emitted as one field entity plus at most one relation fact.
    relation_by_field = {
        row["subject"]["entity_id"]: row.get("qualifier", {})
        for row in rows
        if row["predicate"] == "RELATES_TO_MODEL"
    }
    model_to_fields: dict[str, list[JsonObject]] = {}
    for row in rows:
        if row["predicate"] == "DECLARES_FIELD":
            model_to_fields.setdefault(row["subject"]["entity_id"], []).append(row)

    paths: list[JsonObject] = []
    queue = deque((root, [root], 0) for root in roots)
    seen = set(roots)
    while queue and len(paths) < limit:
        model_id, path, depth = queue.popleft()
        if depth >= 2:
            continue
        for field_row in model_to_fields.get(model_id, []):
            field_id = field_row["object"]["entity_id"]
            target_model = field_to_model.get(field_id)
            if target_model is None:
                continue
            path_row = {
                "model_path": [*path, target_model],
                "via_field": field_row["object"],
                "relation": relation_by_field.get(field_id, {}),
            }
            paths.append(path_row)
            if target_model not in seen:
                seen.add(target_model)
                queue.append((target_model, [*path, target_model], depth + 1))
            if len(paths) >= limit:
                break
    return paths


def _entity_row(entity: JsonObject) -> JsonObject:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return {
        "entity_id": entity.get("entity_id"),
        "kind": entity.get("kind"),
        "name": display_entity(entity),
        "repo": identity.get("repo") or properties.get("repo"),
        "module": identity.get("module"),
        "qualname": identity.get("qualname"),
        "symbol_kind": identity.get("symbol_kind"),
        "properties": properties,
    }


def _entity_repo(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return _normalize_repo(identity.get("repo") or properties.get("repo"))


def _normalize_repo(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-")
    return text or None


_ASSEMBLY_CONTRACT = (
    "Framework impact is assembled from parser-backed support facts only. "
    "Dynamic model lookup, dynamic serializer_class assignment, and runtime task dispatch remain unsupported unless represented by support facts. "
    "If review_context is called without a repo, framework impact returns missing_repo instead of inferring scope."
)
