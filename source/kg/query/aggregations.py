from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from source.kg.core.models import JsonObject


INTERNAL_IMPORT_CATEGORIES = {"internal_module", "relative_internal_module"}
DERIVATION_PRIORITY = {
    "authoritative_declared": 5,
    "runtime_observed": 4,
    "deterministic_static": 3,
    "manual_override": 2,
    "inferred_llm": 1,
}


def who_imports(
    *,
    target: str,
    entities_by_id: dict[str, JsonObject],
    facts: list[JsonObject],
    evidence_by_target: dict[str, list[JsonObject]],
    group_prefix_depth: int = 2,
    no_grouping: bool = False,
    limit: int = 25,
) -> JsonObject:
    resolution = _resolve_import_target(target, facts, entities_by_id)
    if resolution["status"] != "resolved":
        return {**resolution, "importer_count": 0, "returned_count": 0, "groups": [], "importers": []}

    target_id = resolution["resolved_target"]["entity_id"]
    all_importers = [
        _importer_row(fact, entities_by_id, evidence_by_target)
        for fact in _canonical_import_facts(facts, entities_by_id)
        if fact["object_id"] == target_id
    ]
    all_importers = sorted((row for row in all_importers if row), key=lambda row: row["module"])
    importers = all_importers[:limit]
    groups = [] if no_grouping else _group_importers(importers, group_prefix_depth)
    return {
        "status": "resolved" if importers else "empty",
        "target": target,
        "resolved_target_kind": resolution["resolved_target"]["kind"],
        "resolved_target": _entity_ref(resolution["resolved_target"]),
        "importer_count": len(all_importers),
        "returned_count": len(importers),
        "group_prefix_depth": max(1, group_prefix_depth),
        "groups": groups,
        "importers": importers,
    }


def top_internal_dependencies(
    *,
    entities_by_id: dict[str, JsonObject],
    facts: list[JsonObject],
    evidence_by_target: dict[str, list[JsonObject]],
    relative_only: bool = False,
    limit: int = 25,
) -> JsonObject:
    categories = {"relative_internal_module"} if relative_only else INTERNAL_IMPORT_CATEGORIES
    rows_by_target: dict[str, JsonObject] = {}
    importers_by_target: dict[str, set[str]] = defaultdict(set)
    facts_by_target: dict[str, list[JsonObject]] = defaultdict(list)

    for fact in _canonical_import_facts(facts, entities_by_id):
        qualifier = fact.get("qualifier", {})
        if qualifier.get("category") not in categories:
            continue
        target = entities_by_id.get(fact["object_id"])
        source = entities_by_id.get(fact["subject_id"])
        if not target or not source or target.get("kind") != "CodeModule":
            continue
        rows_by_target[fact["object_id"]] = target
        importers_by_target[fact["object_id"]].add(_display(source))
        facts_by_target[fact["object_id"]].append(fact)

    results = [
        {
            "module": _display(target),
            "module_entity_id": target["entity_id"],
            "importer_count": len(importers_by_target[target_id]),
            "importer_samples": sorted(importers_by_target[target_id])[:5],
            **_combined_evidence_summary(facts_by_target[target_id], evidence_by_target),
        }
        for target_id, target in rows_by_target.items()
    ]
    results = sorted(results, key=lambda row: (-row["importer_count"], row["module"]))
    returned = results[:limit]
    return {
        "status": "resolved" if returned else "empty",
        "filter": {"categories": sorted(categories)},
        "result_count": len(results),
        "returned_count": len(returned),
        "results": returned,
    }


def top_fan_in_symbols(
    *,
    entities_by_id: dict[str, JsonObject],
    facts: list[JsonObject],
    evidence_by_target: dict[str, list[JsonObject]],
    include_external: bool = False,
    limit: int = 25,
) -> JsonObject:
    rows_by_target: dict[str, JsonObject] = {}
    callers_by_target: dict[str, set[str]] = defaultdict(set)
    facts_by_target: dict[str, list[JsonObject]] = defaultdict(list)
    external_fact_count = 0

    for fact in _canonical_facts(facts):
        if fact.get("predicate") != "CALLS":
            continue
        target = entities_by_id.get(fact["object_id"])
        source = entities_by_id.get(fact["subject_id"])
        if not target or not source or not _is_canonical_entity(target) or not _is_canonical_entity(source):
            continue
        if target.get("kind") != "CodeSymbol":
            external_fact_count += 1
            if not include_external:
                continue
        rows_by_target[fact["object_id"]] = target
        callers_by_target[fact["object_id"]].add(_display(source))
        facts_by_target[fact["object_id"]].append(fact)

    results = [
        {
            "symbol": _display(target),
            "symbol_entity_id": target["entity_id"],
            "callee_kind": target["kind"],
            "caller_count": len(callers_by_target[target_id]),
            "caller_samples": sorted(callers_by_target[target_id])[:5],
            **_combined_evidence_summary(facts_by_target[target_id], evidence_by_target),
        }
        for target_id, target in rows_by_target.items()
    ]
    results = sorted(results, key=lambda row: (-row["caller_count"], row["symbol"]))
    returned = results[:limit]
    response: JsonObject = {
        "status": "resolved" if returned else "empty",
        "filter": {"include_external": include_external, "callee_kind": "any" if include_external else "CodeSymbol"},
        "result_count": len(results),
        "returned_count": len(returned),
        "results": returned,
    }
    if not returned and not include_external and external_fact_count:
        response["hint"] = "No internal CodeSymbol callees matched; retry with --include-external to include package/module callees."
    return response


def modules_importing_both(
    *,
    left: str,
    right: str,
    entities_by_id: dict[str, JsonObject],
    facts: list[JsonObject],
    evidence_by_target: dict[str, list[JsonObject]],
    category_filter: set[str] | None = None,
    limit: int = 25,
) -> JsonObject:
    left_resolution = _resolve_import_target(left, facts, entities_by_id, category_filter=category_filter)
    right_resolution = _resolve_import_target(right, facts, entities_by_id, category_filter=category_filter)
    if left_resolution["status"] != "resolved" or right_resolution["status"] != "resolved":
        return {
            "status": "ambiguous"
            if "ambiguous" in {left_resolution["status"], right_resolution["status"]}
            else "not_found",
            "left": left_resolution,
            "right": right_resolution,
            "module_count": 0,
            "returned_count": 0,
            "modules": [],
        }

    left_target_id = left_resolution["resolved_target"]["entity_id"]
    right_target_id = right_resolution["resolved_target"]["entity_id"]
    left_by_module = _imports_by_subject(left_target_id, facts, entities_by_id, category_filter)
    right_by_module = _imports_by_subject(right_target_id, facts, entities_by_id, category_filter)
    shared_subject_ids = sorted(set(left_by_module) & set(right_by_module), key=lambda entity_id: _display(entities_by_id[entity_id]))

    modules = []
    for subject_id in shared_subject_ids[:limit]:
        module = entities_by_id[subject_id]
        left_facts = left_by_module[subject_id]
        right_facts = right_by_module[subject_id]
        modules.append(
            {
                "module": _display(module),
                "module_entity_id": module["entity_id"],
                "left_evidence": _import_evidence_rows(left_facts, evidence_by_target),
                "right_evidence": _import_evidence_rows(right_facts, evidence_by_target),
                "left_derivation_class": _combined_evidence_summary(left_facts, evidence_by_target)["derivation_class"],
                "right_derivation_class": _combined_evidence_summary(right_facts, evidence_by_target)["derivation_class"],
                "left_sources_count": _combined_evidence_summary(left_facts, evidence_by_target)["sources_count"],
                "right_sources_count": _combined_evidence_summary(right_facts, evidence_by_target)["sources_count"],
            }
        )

    return {
        "status": "resolved" if modules else "empty",
        "left": _input_resolution_summary(left, left_resolution),
        "right": _input_resolution_summary(right, right_resolution),
        "module_count": len(shared_subject_ids),
        "returned_count": len(modules),
        "modules": modules,
    }


def import_matches_target(fact: JsonObject, target: JsonObject, query: str) -> bool:
    needle = query.lower()
    return needle in {candidate.lower() for candidate in _import_target_candidates(fact, target) if candidate}


def iter_canonical_facts(facts: Iterable[JsonObject]) -> Iterable[JsonObject]:
    for fact in facts:
        if fact.get("canonical_status", "canonical") == "canonical":
            yield fact


def iter_canonical_import_facts(
    facts: Iterable[JsonObject],
    entities_by_id: dict[str, JsonObject],
) -> Iterable[JsonObject]:
    for fact in iter_canonical_facts(facts):
        if fact.get("predicate") != "IMPORTS":
            continue
        source = entities_by_id.get(fact["subject_id"])
        target = entities_by_id.get(fact["object_id"])
        if source and target and is_canonical_entity(source) and is_canonical_entity(target):
            yield fact


def is_canonical_entity(entity: JsonObject) -> bool:
    return _is_canonical_entity(entity)


def resolve_import_target(
    query: str,
    facts: list[JsonObject],
    entities_by_id: dict[str, JsonObject],
    category_filter: set[str] | None = None,
) -> JsonObject:
    return _resolve_import_target(query, facts, entities_by_id, category_filter=category_filter)


def strongest_derivation(evidence_rows: list[JsonObject]) -> str | None:
    return _strongest_derivation(evidence_rows)


def evidence_sample(evidence: JsonObject) -> JsonObject:
    return _evidence_sample(evidence)


def _canonical_facts(facts: Iterable[JsonObject]) -> list[JsonObject]:
    return [fact for fact in facts if fact.get("canonical_status", "canonical") == "canonical"]


def _canonical_import_facts(facts: Iterable[JsonObject], entities_by_id: dict[str, JsonObject]) -> list[JsonObject]:
    rows = []
    for fact in _canonical_facts(facts):
        if fact.get("predicate") != "IMPORTS":
            continue
        source = entities_by_id.get(fact["subject_id"])
        target = entities_by_id.get(fact["object_id"])
        if source and target and _is_canonical_entity(source) and _is_canonical_entity(target):
            rows.append(fact)
    return rows


def _is_canonical_entity(entity: JsonObject) -> bool:
    return entity.get("canonical_status", "canonical") == "canonical"


def _resolve_import_target(
    query: str,
    facts: list[JsonObject],
    entities_by_id: dict[str, JsonObject],
    category_filter: set[str] | None = None,
) -> JsonObject:
    matches: dict[str, JsonObject] = {}
    matched_categories: dict[str, set[str]] = defaultdict(set)
    for fact in _canonical_import_facts(facts, entities_by_id):
        qualifier = fact.get("qualifier", {})
        if category_filter and qualifier.get("category") not in category_filter:
            continue
        target = entities_by_id.get(fact["object_id"])
        if not target or not import_matches_target(fact, target, query):
            continue
        matches[target["entity_id"]] = target
        if qualifier.get("category"):
            matched_categories[target["entity_id"]].add(str(qualifier["category"]))

    candidates = [
        {
            **_entity_ref(entity),
            "matched_categories": sorted(matched_categories[entity_id]),
        }
        for entity_id, entity in sorted(matches.items(), key=lambda item: _display(item[1]))
    ]
    if not candidates:
        return {"status": "not_found", "query": query, "candidates": [], "candidate_count": 0}
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "query": query,
            "candidates": candidates,
            "candidate_count": len(candidates),
        }
    entity = matches[candidates[0]["entity_id"]]
    return {
        "status": "resolved",
        "query": query,
        "resolved_target": entity,
        "candidates": candidates,
        "candidate_count": 1,
    }


def _imports_by_subject(
    target_id: str,
    facts: list[JsonObject],
    entities_by_id: dict[str, JsonObject],
    category_filter: set[str] | None,
) -> dict[str, list[JsonObject]]:
    by_subject: dict[str, list[JsonObject]] = defaultdict(list)
    for fact in _canonical_import_facts(facts, entities_by_id):
        if fact["object_id"] != target_id:
            continue
        if category_filter and fact.get("qualifier", {}).get("category") not in category_filter:
            continue
        by_subject[fact["subject_id"]].append(fact)
    return by_subject


def _importer_row(
    fact: JsonObject,
    entities_by_id: dict[str, JsonObject],
    evidence_by_target: dict[str, list[JsonObject]],
) -> JsonObject | None:
    module = entities_by_id.get(fact["subject_id"])
    if not module:
        return None
    return {
        "module": _display(module),
        "module_entity_id": module["entity_id"],
        "fact_id": fact["fact_id"],
        "qualifier": fact.get("qualifier", {}),
        **_combined_evidence_summary([fact], evidence_by_target),
    }


def _group_importers(importers: list[JsonObject], group_prefix_depth: int) -> list[JsonObject]:
    depth = max(1, group_prefix_depth)
    groups: dict[str, list[JsonObject]] = defaultdict(list)
    for importer in importers:
        groups[_module_prefix(importer["module"], depth)].append(importer)
    return [
        {
            "group_key": group_key,
            "importer_count": len(rows),
            "importers": rows,
        }
        for group_key, rows in sorted(groups.items(), key=lambda item: item[0])
    ]


def _module_prefix(module_name: str, depth: int) -> str:
    parts = [part for part in module_name.split(".") if part]
    return ".".join(parts[:depth]) if parts else module_name


def _combined_evidence_summary(facts: list[JsonObject], evidence_by_target: dict[str, list[JsonObject]]) -> JsonObject:
    evidence_rows = []
    for fact in facts:
        evidence_rows.extend(evidence_by_target.get(fact["fact_id"], []))
    derivation_class = _strongest_derivation(evidence_rows)
    source_systems = {str(row.get("source_system")) for row in evidence_rows if row.get("source_system")}
    return {
        "derivation_class": derivation_class,
        "sources_count": len(source_systems),
        "evidence_samples": [_evidence_sample(row) for row in evidence_rows[:3]],
    }


def _strongest_derivation(evidence_rows: list[JsonObject]) -> str | None:
    if not evidence_rows:
        return None
    return max(
        (str(row.get("derivation_class")) for row in evidence_rows if row.get("derivation_class")),
        key=lambda value: DERIVATION_PRIORITY.get(value, 0),
        default=None,
    )


def _evidence_sample(evidence: JsonObject) -> JsonObject:
    bytes_ref = evidence.get("bytes_ref") or {}
    return {
        "repo": bytes_ref.get("repo"),
        "commit_sha": bytes_ref.get("commit_sha"),
        "path": bytes_ref.get("path"),
        "line_start": bytes_ref.get("line_start"),
        "line_end": bytes_ref.get("line_end"),
        "source_system": evidence.get("source_system"),
        "derivation_class": evidence.get("derivation_class"),
    }


def _import_evidence_rows(facts: list[JsonObject], evidence_by_target: dict[str, list[JsonObject]]) -> list[JsonObject]:
    rows = []
    for fact in facts[:3]:
        for evidence in evidence_by_target.get(fact["fact_id"], [])[:1]:
            rows.append(
                {
                    **_evidence_sample(evidence),
                    "fact_id": fact["fact_id"],
                    "qualifier": fact.get("qualifier", {}),
                }
            )
    return rows


def _input_resolution_summary(query: str, resolution: JsonObject) -> JsonObject:
    target = resolution.get("resolved_target")
    candidates = resolution.get("candidates", [])
    return {
        "query": query,
        "status": resolution["status"],
        "matched_categories": candidates[0].get("matched_categories", []) if candidates else [],
        "matched_targets": [_display(target)] if target else [candidate.get("display_name") for candidate in candidates],
    }


def _import_target_candidates(fact: JsonObject, target: JsonObject) -> set[str]:
    identity = target.get("identity", {})
    qualifier = fact.get("qualifier", {})
    return {
        str(identity.get("name", "")),
        str(identity.get("module", "")),
        str(qualifier.get("raw_import", "")),
        str(qualifier.get("import_root", "")),
        str(qualifier.get("distribution_name", "")),
        str(qualifier.get("module_name", "")),
    }


def _entity_ref(entity: JsonObject) -> JsonObject:
    return {
        "entity_id": entity["entity_id"],
        "kind": entity["kind"],
        "display_name": _display(entity),
        "identity": entity.get("identity", {}),
    }


def _display(entity: JsonObject) -> str:
    identity = entity["identity"]
    if entity["kind"] == "CodeSymbol":
        return f"{identity.get('module')}.{identity.get('qualname')}"
    if entity["kind"] == "CodeModule":
        return str(identity.get("module"))
    if entity["kind"] == "EventChannel":
        return f"{identity.get('broker_kind')}:{identity.get('channel_address') or identity.get('name')}"
    return str(identity.get("name") or identity.get("slug") or identity)
