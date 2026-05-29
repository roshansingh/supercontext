from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from source.kg.core.models import JsonObject

if TYPE_CHECKING:
    from source.kg.query.snapshot import KgSnapshot

PREVIEW_CALLER_SAMPLE_LIMIT = 3
INSPECTION_SEARCH_TERM_LIMIT = 8
INSPECTION_PATH_HINT_LIMIT = 8
INSPECTION_REPO_LIMIT = 8


def reverse_impact_packet(
    kg: KgSnapshot,
    symbol_query: str,
    *,
    depth: int,
    limit: int,
    path: str | None = None,
    line: int | None = None,
    include_all: bool = False,
) -> JsonObject:
    resolution = kg._resolve_symbol(symbol_query, limit=limit, path=path, line=line, allow_fuzzy=False)
    if resolution["status"] == "not_found":
        return {
            "status": "not_found",
            "source": resolution,
            "depth": depth,
            "summary": _empty_summary(depth=depth, limit=limit),
            "roots": [],
            "tiers": [],
            "edges": [],
            "constructor_bridges": [],
            "terminal_import_consumer_leads": [],
            "truncated_terminal_symbols": [],
            "source_inspection_areas": _source_inspection_areas([], query=symbol_query, candidates=[]),
            "affected_symbols": [],
            "answerability": _answerability("not_found"),
            "contract": _CONTRACT,
        }
    if resolution["status"] == "ambiguous" and not include_all:
        candidates = [row for row in resolution.get("candidates", []) if isinstance(row, dict)]
        return {
            **kg._symbol_disambiguation_payload(resolution, result_kind="reverse impact"),
            "status": "ambiguous",
            "source": resolution,
            "mode": "ambiguous",
            "depth": depth,
            "summary": _empty_summary(depth=depth, limit=limit),
            "roots": [],
            "tiers": [],
            "edges": [],
            "constructor_bridges": [],
            "terminal_import_consumer_leads": [],
            "truncated_terminal_symbols": [],
            "affected_symbols": [],
            "candidate_impact_previews": _candidate_impact_previews(kg, resolution, limit=limit),
            "source_inspection_areas": _source_inspection_areas([], query=symbol_query, candidates=candidates),
            "ambiguity_guidance": _AMBIGUITY_GUIDANCE,
            "answerability": _answerability("ambiguous"),
            "contract": _CONTRACT,
        }

    root_symbols = _root_symbols(kg, resolution, include_all=include_all)
    roots = [kg._symbol_result(symbol) for symbol in root_symbols]
    result = _walk_reverse_impact(kg, root_symbols, depth=depth, limit=limit)
    if result["edges"]:
        status = "found"
    elif result["terminal_import_consumer_leads"]:
        status = "partial"
    else:
        status = "not_found"
    if resolution["status"] == "ambiguous" and include_all:
        answerability_status = "partial_ambiguous"
    elif status == "partial":
        answerability_status = "partial_import_leads"
    else:
        answerability_status = status
    return {
        "status": status,
        "source": resolution,
        "mode": "all_matching_symbols" if resolution["status"] == "ambiguous" and include_all else "exact_symbol",
        "depth": depth,
        "summary": {
            "root_symbol_count": len(root_symbols),
            "affected_symbol_count": result["affected_symbol_total_count"],
            "affected_symbol_returned_count": len(result["affected_symbols"]),
            "edge_count": len(result["edges"]),
            "constructor_bridge_count": result["constructor_bridge_total_count"],
            "constructor_bridge_returned_count": len(result["constructor_bridges"]),
            "terminal_import_lead_count": result["terminal_import_lead_total_count"],
            "terminal_import_lead_returned_count": sum(
                _safe_int(row.get("import_consumer_leads", {}).get("returned_count"))
                for row in result["terminal_import_consumer_leads"]
            ),
            "terminal_import_lead_total_in_returned_rows": sum(
                _safe_int(row.get("import_consumer_leads", {}).get("lead_count"))
                for row in result["terminal_import_consumer_leads"]
            ),
            "max_depth_terminal_count": sum(
                1
                for row in result["terminal_import_consumer_leads"]
                if row.get("terminal_reason") == "max_depth_reached"
            ),
            "truncated": result["truncated"],
            "walk_truncated": result["walk_truncated"],
            "affected_symbols_truncated": result["affected_symbols_truncated"],
            "constructor_bridges_truncated": result["constructor_bridges_truncated"],
            "terminal_import_leads_truncated": result["terminal_import_leads_truncated"],
            "truncated_terminal_symbol_count": result["truncated_terminal_symbol_total_count"],
            "truncated_terminal_symbol_returned_count": len(result["truncated_terminal_symbols"]),
            "roots_unexpanded_count": result["roots_unexpanded_count"],
            "section_limit": limit,
            "max_depth": depth,
            "edge_multiplicity": "per_root" if resolution["status"] == "ambiguous" and include_all else "unique",
            "affected_symbol_multiplicity": "unique_global",
            "tier_symbol_multiplicity": "unique_global",
            "affected_root_projection": "root_symbols_list_with_shortest_depth_root_symbol",
        },
        "roots": roots,
        "tiers": _impact_tiers(result["affected_symbol_rows_for_tiers"], limit=limit),
        "edges": result["edges"],
        "constructor_bridges": result["constructor_bridges"],
        "terminal_import_consumer_leads": result["terminal_import_consumer_leads"],
        "truncated_terminal_symbols": result["truncated_terminal_symbols"],
        "source_inspection_areas": _source_inspection_areas(roots, query=symbol_query, candidates=[]),
        "affected_symbols": result["affected_symbols"],
        "answerability": _answerability(answerability_status),
        "contract": _CONTRACT,
    }


_CONTRACT = (
    "reverse_impact walks incoming static CALLS facts from the changed symbol to bounded callers. "
    "It is a source-inspection head start, not runtime proof. Constructor bridging maps a reached __init__ "
    "method to its containing class so class instantiation callers are visible. Terminal import_consumer_leads "
    "are source leads only and must be verified before claiming runtime execution. In include_all mode, affected "
    "symbols are unique globally; root_symbol is the shortest-depth representative and root_symbols lists all roots "
    "that reached the affected symbol within the bounded walk. A constructor bridge row is recorded at the reached "
    "__init__ depth; callers discovered through the bridged class target appear one reverse-call depth higher. The "
    "section limit is global across roots; if the walk truncates before all roots expand, summary.roots_unexpanded_count "
    "and truncated_terminal_symbols report that loss of coverage. truncated_before_expansion marks the next queued "
    "symbol whose remaining incoming callers were not explored after the global section limit was reached."
)

_AMBIGUITY_GUIDANCE = (
    "This unqualified symbol matched multiple candidates. Do not aggregate all candidates unless the user asks for all "
    "matches or exploratory impact. For a single-symbol answer, choose one exact candidate only when the user supplied "
    "a repo/path/line, a previous disambiguation candidate gives that location, or explicit source evidence identifies "
    "the intended edit site; otherwise report the ambiguity and ask for path/line. Candidate impact preview rank is a "
    "scan-order hint, not proof of user intent."
)


def _empty_summary(*, depth: int, limit: int) -> JsonObject:
    return {
        "root_symbol_count": 0,
        "affected_symbol_count": 0,
        "affected_symbol_returned_count": 0,
        "edge_count": 0,
        "constructor_bridge_count": 0,
        "constructor_bridge_returned_count": 0,
        "terminal_import_lead_count": 0,
        "terminal_import_lead_returned_count": 0,
        "terminal_import_lead_total_in_returned_rows": 0,
        "max_depth_terminal_count": 0,
        "truncated": False,
        "walk_truncated": False,
        "affected_symbols_truncated": False,
        "constructor_bridges_truncated": False,
        "terminal_import_leads_truncated": False,
        "truncated_terminal_symbol_count": 0,
        "truncated_terminal_symbol_returned_count": 0,
        "roots_unexpanded_count": 0,
        "section_limit": limit,
        "max_depth": depth,
        "edge_multiplicity": "unique",
        "affected_symbol_multiplicity": "unique_global",
        "tier_symbol_multiplicity": "unique_global",
        "affected_root_projection": "root_symbols_list_with_shortest_depth_root_symbol",
    }


def _answerability(status: str) -> JsonObject:
    if status == "found":
        return {
            "status": "partial",
            "missing_fact_families": [],
            "recommended_source_checks": [
                "Verify returned caller chains in source before finalizing a change-impact answer.",
                "Treat terminal_import_consumer_leads as inspection leads, not proven runtime calls.",
                "Inspect source_inspection_areas for tests, scripts, notebooks, and entry-point imports outside the returned CALLS graph.",
            ],
        }
    if status == "ambiguous":
        return {
            "status": "not_answerable",
            "missing_fact_families": ["unambiguous_primary_anchor"],
            "recommended_source_checks": [
                "Pick one exact candidate from disambiguation.retry_arguments only when user-provided location or source evidence identifies the intended edit site.",
                "Use include_all only when the user asks for all matching symbols or exploratory aggregation.",
            ],
        }
    if status == "partial_ambiguous":
        return {
            "status": "partial",
            "missing_fact_families": ["unambiguous_primary_anchor"],
            "recommended_source_checks": [
                "This aggregates multiple matching symbols; verify which candidate is the intended edit site."
            ],
        }
    if status == "partial_import_leads":
        return {
            "status": "partial",
            "missing_fact_families": ["reverse_callers"],
            "recommended_source_checks": [
                "Only import-consumer inspection leads were found; inspect source before treating them as runtime callers."
            ],
        }
    return {
        "status": "partial",
        "missing_fact_families": ["reverse_callers"],
        "recommended_source_checks": [
            "No indexed reverse-impact callers were found; inspect source before treating this as no impact."
        ],
    }


def _root_symbols(kg: KgSnapshot, resolution: JsonObject, *, include_all: bool) -> list[JsonObject]:
    if include_all:
        ids = [candidate.get("symbol_id") for candidate in resolution.get("candidates", [])]
    else:
        resolved = resolution.get("resolved_symbol")
        ids = [resolved.get("symbol_id")] if isinstance(resolved, dict) else []
    symbols = []
    for symbol_id in ids:
        symbol = kg.entities_by_id.get(symbol_id)
        if symbol and symbol.get("kind") == "CodeSymbol":
            symbols.append(symbol)
    return symbols


def _walk_reverse_impact(kg: KgSnapshot, roots: list[JsonObject], *, depth: int, limit: int) -> JsonObject:
    incoming = _incoming_call_facts(kg)
    class_symbols = _class_symbol_index(kg)
    root_by_id = {str(symbol["entity_id"]): kg._symbol_result(symbol) for symbol in roots}
    queue = deque((str(symbol["entity_id"]), 0, str(symbol["entity_id"])) for symbol in roots)
    expanded: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()
    seen_bridges: set[tuple[str, str, str]] = set()
    affected_by_id: dict[str, JsonObject] = {}
    terminal_by_id: dict[tuple[str, str], JsonObject] = {}
    edges: list[JsonObject] = []
    bridges: list[JsonObject] = []
    expanded_roots: set[str] = set()
    truncated = False

    while queue:
        current_id, current_depth, root_id = queue.popleft()
        if current_id == root_id:
            expanded_roots.add(root_id)
        expand_key = (root_id, current_id)
        if current_depth >= depth:
            if expand_key not in expanded:
                terminal_by_id.setdefault(
                    (root_id, current_id),
                    {
                        "depth": current_depth,
                        "root_id": root_id,
                        "terminal_reason": "max_depth_reached",
                    },
                )
            continue
        if expand_key in expanded:
            continue
        expanded.add(expand_key)

        targets = [(current_id, None)]
        current_symbol = kg.entities_by_id.get(current_id)
        bridge = (
            _constructor_bridge_for_symbol(kg, current_symbol, depth=current_depth, class_symbols=class_symbols)
            if current_symbol
            else None
        )
        if bridge:
            bridge_key = (
                root_id,
                str(bridge["from_init"].get("symbol_id")),
                str(bridge["to_class"].get("symbol_id")),
            )
            if bridge_key not in seen_bridges:
                seen_bridges.add(bridge_key)
                bridges.append({**bridge, "root_symbol": root_by_id.get(root_id, {})})
            class_id = bridge["to_class"].get("symbol_id")
            if isinstance(class_id, str):
                targets.append((class_id, bridge))

        found_incoming = False
        for target_id, active_bridge in targets:
            for fact in incoming.get(target_id, []):
                caller = kg.entities_by_id.get(fact.get("subject_id"))
                callee = kg.entities_by_id.get(fact.get("object_id"))
                if not caller or not callee:
                    continue
                if str(caller.get("entity_id")) == root_id:
                    continue
                edge_key = (root_id, str(fact.get("fact_id")), str(caller.get("entity_id")), str(callee.get("entity_id")))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                found_incoming = True
                edge_depth = current_depth + 1
                caller_ref = kg._symbol_result(caller)
                row = kg._fact_result(
                    fact,
                    caller,
                    callee,
                    depth=edge_depth,
                    traversal="reverse_call",
                    root_symbol=root_by_id.get(root_id, {}),
                    caller_symbol=caller_ref,
                    callee_symbol=kg._symbol_result(callee),
                )
                if active_bridge:
                    row["via_constructor_bridge"] = active_bridge
                edges.append(row)
                affected_key = str(caller["entity_id"])
                existing = affected_by_id.get(affected_key)
                root_symbol = root_by_id.get(root_id, {})
                if existing is None:
                    affected_by_id[affected_key] = {
                        "symbol": caller_ref,
                        "depth": edge_depth,
                        "root_symbol": root_symbol,
                        "root_symbols": [root_symbol] if root_symbol else [],
                    }
                else:
                    root_symbols = existing.setdefault("root_symbols", [])
                    if isinstance(root_symbols, list) and root_symbol and root_symbol not in root_symbols:
                        root_symbols.append(root_symbol)
                    if edge_depth < _safe_int(existing.get("depth")):
                        existing["depth"] = edge_depth
                        existing["root_symbol"] = root_symbol
                if len(edges) >= limit:
                    truncated = True
                    _mark_truncated_terminals(
                        terminal_by_id,
                        queue=queue,
                        parent_symbol_id=current_id,
                        parent_depth=current_depth,
                        current_symbol_id=str(caller["entity_id"]),
                        current_depth=edge_depth,
                        current_root_id=root_id,
                        current_reason="truncated_after_incoming_edge",
                    )
                    queue.clear()
                    break
                queue.append((str(caller["entity_id"]), edge_depth, root_id))
            if truncated:
                break
        if not found_incoming:
            terminal_by_id[(root_id, current_id)] = {
                "depth": current_depth,
                "root_id": root_id,
                "terminal_reason": "no_incoming_callers",
            }

    terminal_leads = _terminal_import_leads(
        kg,
        terminal_by_id,
        affected_by_id=affected_by_id,
        root_by_id=root_by_id,
        limit=limit,
    )
    truncated_terminals = _truncated_terminal_symbols(
        kg,
        terminal_by_id,
        affected_by_id=affected_by_id,
        root_by_id=root_by_id,
        limit=limit,
    )
    sorted_affected = _sorted_affected_symbols(affected_by_id.values())
    return {
        "edges": edges,
        "constructor_bridges": bridges[:limit],
        "terminal_import_consumer_leads": terminal_leads[:limit],
        "truncated_terminal_symbols": truncated_terminals[: max(limit, 2)],
        "affected_symbols": sorted_affected[:limit],
        "affected_symbol_rows_for_tiers": sorted_affected,
        "affected_symbol_total_count": len(affected_by_id),
        "constructor_bridge_total_count": len(bridges),
        "terminal_import_lead_total_count": sum(
            _safe_int(row.get("import_consumer_leads", {}).get("lead_count")) for row in terminal_leads
        ),
        "truncated_terminal_symbol_total_count": len(truncated_terminals),
        "walk_truncated": truncated,
        "affected_symbols_truncated": truncated or len(affected_by_id) > limit,
        "constructor_bridges_truncated": len(bridges) > limit,
        "terminal_import_leads_truncated": len(terminal_leads) > limit,
        "roots_unexpanded_count": len(set(root_by_id) - expanded_roots),
        "truncated": truncated or len(bridges) > limit or len(terminal_leads) > limit or len(affected_by_id) > limit,
    }


def _mark_truncated_terminals(
    terminal_by_id: dict[tuple[str, str], JsonObject],
    *,
    queue: deque[tuple[str, int, str]],
    parent_symbol_id: str,
    parent_depth: int,
    current_symbol_id: str,
    current_depth: int,
    current_root_id: str,
    current_reason: str,
) -> None:
    terminal_by_id.setdefault(
        (current_root_id, parent_symbol_id),
        {
            "depth": parent_depth,
            "root_id": current_root_id,
            "terminal_reason": "truncated_before_expansion",
        },
    )
    terminal_by_id.setdefault(
        (current_root_id, current_symbol_id),
        {
            "depth": current_depth,
            "root_id": current_root_id,
            "terminal_reason": current_reason,
        },
    )
    for queued_symbol_id, queued_depth, queued_root_id in queue:
        terminal_by_id.setdefault(
            (queued_root_id, queued_symbol_id),
            {
                "depth": queued_depth,
                "root_id": queued_root_id,
                "terminal_reason": "truncated_before_expansion",
            },
        )


def _class_symbol_index(kg: KgSnapshot) -> dict[tuple[object, object, object, object], JsonObject]:
    cached = getattr(kg, "_reverse_impact_class_symbol_index_cache", None)
    if cached is not None:
        return cached
    index = {}
    for entity in kg.entities:
        if entity.get("kind") != "CodeSymbol":
            continue
        identity = entity.get("identity", {})
        if identity.get("symbol_kind") != "class":
            continue
        index[
            (
                identity.get("tenant_id"),
                identity.get("repo"),
                identity.get("module"),
                identity.get("qualname"),
            )
        ] = entity
    kg._reverse_impact_class_symbol_index_cache = index
    return index


def _init_symbol_index(kg: KgSnapshot) -> dict[tuple[object, object, object, object], JsonObject]:
    cached = getattr(kg, "_reverse_impact_init_symbol_index_cache", None)
    if cached is not None:
        return cached
    index = {}
    for entity in kg.entities:
        if entity.get("kind") != "CodeSymbol":
            continue
        identity = entity.get("identity", {})
        qualname = identity.get("qualname")
        if identity.get("symbol_kind") != "method" or not isinstance(qualname, str) or not qualname.endswith(".__init__"):
            continue
        index[
            (
                identity.get("tenant_id"),
                identity.get("repo"),
                identity.get("module"),
                qualname,
            )
        ] = entity
    kg._reverse_impact_init_symbol_index_cache = index
    return index


def _incoming_call_facts(kg: KgSnapshot) -> dict[str, list[JsonObject]]:
    cached = getattr(kg, "_reverse_impact_incoming_call_facts_cache", None)
    if cached is not None:
        return cached
    incoming: dict[str, list[JsonObject]] = defaultdict(list)
    for fact in kg.facts:
        if fact.get("predicate") == "CALLS":
            object_id = fact.get("object_id")
            if isinstance(object_id, str):
                incoming[object_id].append(fact)
    kg._reverse_impact_incoming_call_facts_cache = incoming
    return incoming


def _constructor_bridge_for_symbol(
    kg: KgSnapshot,
    symbol: JsonObject | None,
    *,
    depth: int,
    class_symbols: dict[tuple[object, object, object, object], JsonObject],
) -> JsonObject | None:
    if not symbol or symbol.get("kind") != "CodeSymbol":
        return None
    identity = symbol.get("identity", {})
    qualname = identity.get("qualname")
    if not isinstance(qualname, str) or not qualname.endswith(".__init__"):
        return None
    class_qualname = qualname[: -len(".__init__")]
    candidate = class_symbols.get(
        (
            identity.get("tenant_id"),
            identity.get("repo"),
            identity.get("module"),
            class_qualname,
        )
    )
    if candidate is None:
        return None
    return {
        "depth": depth,
        "bridge_kind": "constructor_init_to_class",
        "reason": "Python constructor calls target the class symbol, while __init__ contains constructor body impact.",
        "from_init": kg._symbol_result(symbol),
        "to_class": kg._symbol_result(candidate),
    }


def _terminal_import_leads(
    kg: KgSnapshot,
    terminal_by_id: dict[tuple[str, str], JsonObject],
    *,
    affected_by_id: dict[str, JsonObject],
    root_by_id: dict[str, JsonObject],
    limit: int,
) -> list[JsonObject]:
    rows = []
    for (root_id, symbol_id), terminal in _sorted_terminal_items(kg, terminal_by_id):
        symbol = kg.entities_by_id.get(symbol_id)
        if not symbol or symbol.get("kind") != "CodeSymbol":
            continue
        leads = kg._symbol_import_consumer_leads(_single_symbol_resolution(kg, symbol), limit=limit)
        if leads.get("status") != "found":
            continue
        affected = affected_by_id.get(symbol_id, {})
        rows.append(
            {
                "for_symbol": kg._symbol_result(symbol),
                "depth": terminal.get("depth", affected.get("depth", 0)),
                "terminal_reason": terminal.get("terminal_reason"),
                "root_symbol": root_by_id.get(root_id, {}),
                "import_consumer_leads": leads,
            }
        )
    return rows


def _truncated_terminal_symbols(
    kg: KgSnapshot,
    terminal_by_id: dict[tuple[str, str], JsonObject],
    *,
    affected_by_id: dict[str, JsonObject],
    root_by_id: dict[str, JsonObject],
    limit: int,
) -> list[JsonObject]:
    rows = []
    for (root_id, symbol_id), terminal in _sorted_terminal_items(kg, terminal_by_id):
        terminal_reason = terminal.get("terminal_reason")
        if terminal_reason not in {"truncated_after_incoming_edge", "truncated_before_expansion"}:
            continue
        symbol = kg.entities_by_id.get(symbol_id)
        if not symbol or symbol.get("kind") != "CodeSymbol":
            continue
        affected = affected_by_id.get(symbol_id, {})
        rows.append(
            {
                "symbol": kg._symbol_result(symbol),
                "depth": terminal.get("depth", affected.get("depth", 0)),
                "terminal_reason": terminal_reason,
                "root_symbol": root_by_id.get(root_id, {}),
                "inspection_hint": "Reverse walk stopped here because the global section limit was reached.",
            }
        )
    return rows


def _sorted_terminal_items(
    kg: KgSnapshot, terminal_by_id: dict[tuple[str, str], JsonObject]
) -> list[tuple[tuple[str, str], JsonObject]]:
    return sorted(
        terminal_by_id.items(),
        key=lambda item: _terminal_sort_key(kg, item[0], item[1]),
    )


def _terminal_sort_key(kg: KgSnapshot, key: tuple[str, str], terminal: JsonObject) -> tuple[int, int, str, int, str, str]:
    root_id, symbol_id = key
    symbol = kg.entities_by_id.get(symbol_id)
    row = kg._symbol_result(symbol) if symbol and symbol.get("kind") == "CodeSymbol" else {}
    return (
        _terminal_reason_rank(terminal.get("terminal_reason")),
        _safe_int(terminal.get("depth")),
        str(row.get("path") or ""),
        _safe_int(row.get("line")),
        str(row.get("qualified_name") or ""),
        root_id,
    )


def _terminal_reason_rank(value: object) -> int:
    if value == "truncated_before_expansion":
        return 0
    if value == "truncated_after_incoming_edge":
        return 1
    if value == "max_depth_reached":
        return 2
    if value == "no_incoming_callers":
        return 3
    return 4


def _single_symbol_resolution(kg: KgSnapshot, symbol: JsonObject) -> JsonObject:
    row = kg._symbol_result(symbol)
    return {
        "status": "resolved",
        "query": row.get("qualified_name") or row.get("qualname") or "",
        "confidence": "exact_unique",
        "resolved_symbol": row,
        "candidates": [row],
        "candidate_count": 1,
    }


def _candidate_impact_previews(kg: KgSnapshot, resolution: JsonObject, *, limit: int) -> list[JsonObject]:
    incoming = _incoming_call_facts(kg)
    class_symbols = _class_symbol_index(kg)
    init_symbols = _init_symbol_index(kg)
    previews = []
    for candidate in list(resolution.get("candidates", []))[:limit]:
        symbol_id = candidate.get("symbol_id")
        if not isinstance(symbol_id, str):
            continue
        symbol = kg.entities_by_id.get(symbol_id)
        target_ids = _candidate_preview_target_ids(
            kg,
            symbol,
            class_symbols=class_symbols,
            init_symbols=init_symbols,
        )
        facts_by_id: dict[str, JsonObject] = {}
        for target_id in target_ids:
            for fact in incoming.get(target_id, []):
                fact_id = fact.get("fact_id")
                if isinstance(fact_id, str):
                    facts_by_id.setdefault(fact_id, fact)
        facts = list(facts_by_id.values())
        caller_samples = []
        for fact in facts[:PREVIEW_CALLER_SAMPLE_LIMIT]:
            caller = kg.entities_by_id.get(fact.get("subject_id"))
            callee = kg.entities_by_id.get(fact.get("object_id"))
            if caller and callee:
                caller_samples.append(kg._fact_result(fact, caller, callee))
        previews.append(
            {
                "symbol": candidate,
                "direct_caller_count": len(facts),
                "selection_basis": (
                    "previewed_direct_caller_count; constructor targets are included for classes and __init__ methods, "
                    "so this can differ from find_callers on the exact symbol"
                ),
                "caller_samples": caller_samples,
                "retry_arguments": kg._symbol_retry_arguments(candidate, str(resolution.get("query", ""))),
            }
        )
    ranked = sorted(
        previews,
        key=lambda row: (
            -_safe_int(row.get("direct_caller_count")),
            _candidate_kind_rank(row.get("symbol")),
            str(row.get("symbol", {}).get("path") or ""),
            _safe_int(row.get("symbol", {}).get("line")),
            str(row.get("symbol", {}).get("qualified_name") or ""),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["impact_preview_rank"] = index
    return ranked


def _source_inspection_areas(
    root_symbols: list[JsonObject], *, query: str, candidates: list[JsonObject]
) -> list[JsonObject]:
    symbol_rows = root_symbols or candidates
    search_terms = _inspection_search_terms(symbol_rows, query=query)
    if not search_terms:
        return []
    repos = _bounded_sorted_values(
        (_symbol_value(row, "repo") for row in symbol_rows),
        limit=INSPECTION_REPO_LIMIT,
    )
    path_hints = _bounded_sorted_values(
        (_symbol_value(row, "path") for row in symbol_rows if _symbol_value(row, "path") is not None),
        limit=INSPECTION_PATH_HINT_LIMIT,
    )
    area: JsonObject = {
        "area": "same_repo_tests_scripts_notebooks" if repos else "workspace_reference_search",
        "reason": (
            "The reverse-impact graph is a bounded CALLS head start. Tests, scripts, notebooks, dynamic entry points, "
            "and import-only consumers may need source inspection before final claims."
        ),
        "search_terms": search_terms,
        "scope_hint": (
            "Search the same repo first when repos are listed; include tests, scripts, notebooks, routes/views, "
            "CLI entry points, and modules that import the anchor without an indexed CALLS edge."
        ),
    }
    if repos:
        area["repos"] = repos[:INSPECTION_REPO_LIMIT]
    if path_hints:
        area["path_hints"] = path_hints
    return [area]


def _inspection_search_terms(symbol_rows: list[JsonObject], *, query: str) -> list[str]:
    terms: list[str] = []
    clean_query = query.strip()
    if clean_query:
        terms.append(clean_query)
    for row in symbol_rows:
        qualified_name = _symbol_value(row, "qualified_name")
        module = _symbol_value(row, "module")
        qualname = _symbol_value(row, "qualname")
        symbol_kind = _symbol_value(row, "symbol_kind")
        simple_name = _simple_symbol_name(qualname or qualified_name)
        if simple_name and symbol_kind in {"function", "method", "class"}:
            terms.append(f"{simple_name}(")
        if qualified_name:
            terms.append(qualified_name)
        if module and simple_name and symbol_kind in {"function", "method", "class"}:
            terms.append(f"{module.rsplit('.', 1)[-1]}.{simple_name}")
        if qualname and "." in qualname:
            terms.append(qualname)
    return _dedupe_strings_bounded(terms, limit=INSPECTION_SEARCH_TERM_LIMIT)


def _symbol_value(row: JsonObject, key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, str) and value:
        return value
    identity = row.get("identity")
    if isinstance(identity, dict):
        value = identity.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _simple_symbol_name(value: str | None) -> str | None:
    if not value:
        return None
    return value.rsplit(".", 1)[-1]


def _bounded_sorted_values(values: object, *, limit: int) -> list[str]:
    return sorted(_dedupe_strings_bounded([value for value in values if isinstance(value, str)], limit=limit))


def _dedupe_strings_bounded(values: list[str], *, limit: int) -> list[str]:
    rows = []
    seen = set()
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        rows.append(clean)
        if len(rows) >= limit:
            break
    return rows


def _candidate_preview_target_ids(
    kg: KgSnapshot,
    symbol: JsonObject | None,
    *,
    class_symbols: dict[tuple[object, object, object, object], JsonObject],
    init_symbols: dict[tuple[object, object, object, object], JsonObject],
) -> list[str]:
    if not symbol:
        return []
    symbol_id = symbol.get("entity_id")
    target_ids = [symbol_id] if isinstance(symbol_id, str) else []
    bridge = _constructor_bridge_for_symbol(kg, symbol, depth=0, class_symbols=class_symbols)
    class_id = bridge.get("to_class", {}).get("symbol_id") if bridge else None
    if isinstance(class_id, str) and class_id not in target_ids:
        target_ids.append(class_id)
    init_id = _init_symbol_for_class_candidate(symbol, init_symbols=init_symbols)
    if isinstance(init_id, str) and init_id not in target_ids:
        target_ids.append(init_id)
    return target_ids


def _init_symbol_for_class_candidate(
    symbol: JsonObject | None,
    *,
    init_symbols: dict[tuple[object, object, object, object], JsonObject],
) -> str | None:
    if not symbol or symbol.get("kind") != "CodeSymbol":
        return None
    identity = symbol.get("identity", {})
    if identity.get("symbol_kind") != "class":
        return None
    qualname = identity.get("qualname")
    if not isinstance(qualname, str) or not qualname:
        return None
    candidate = init_symbols.get(
        (
            identity.get("tenant_id"),
            identity.get("repo"),
            identity.get("module"),
            f"{qualname}.__init__",
        )
    )
    symbol_id = candidate.get("entity_id") if candidate else None
    return symbol_id if isinstance(symbol_id, str) else None


def _candidate_kind_rank(value: object) -> int:
    if not isinstance(value, dict):
        return 99
    symbol_kind = value.get("symbol_kind")
    if symbol_kind in {"function", "class"}:
        return 0
    if symbol_kind == "method":
        return 1
    return 2


def _impact_tiers(affected_symbols: list[JsonObject], *, limit: int) -> list[JsonObject]:
    by_depth: dict[int, list[JsonObject]] = defaultdict(list)
    for row in affected_symbols:
        depth = row.get("depth")
        if isinstance(depth, bool) or not isinstance(depth, int):
            continue
        by_depth[depth].append(row)
    tiers = []
    for depth, rows in sorted(by_depth.items()):
        tiers.append({"depth": depth, "symbols": rows[:limit], "symbol_count": len(rows)})
    return tiers


def _sorted_affected_symbols(rows: object) -> list[JsonObject]:
    return sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda row: (
            _safe_int(row.get("depth")),
            str(row.get("symbol", {}).get("path") or ""),
            _safe_int(row.get("symbol", {}).get("line")),
            str(row.get("symbol", {}).get("qualified_name") or ""),
        ),
    )


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
