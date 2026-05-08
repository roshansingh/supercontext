from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from source.kg import aggregations
from source.kg.models import JsonObject


_ADJACENCY_CACHE_ATTR = "_dependency_path_adjacency"


@dataclass(frozen=True)
class Edge:
    fact_id: str
    predicate: str
    direction: str
    to_entity_id: str
    qualifier: JsonObject


@dataclass(frozen=True)
class Path:
    nodes: tuple[str, ...]
    edges: tuple[Edge, ...]

    @property
    def depth(self) -> int:
        return len(self.edges)


def find_dependency_paths(
    snapshot: Any,
    source_entity_ids: set[str],
    target_resolution: JsonObject,
    *,
    max_depth: int,
    limit: int,
) -> list[Path]:
    target_ids = _target_entity_ids(target_resolution)
    if not source_entity_ids or not target_ids:
        return []

    adjacency = _adjacency(snapshot)
    queue = deque((source_id, (source_id,), tuple()) for source_id in sorted(source_entity_ids))
    paths: list[Path] = []
    seen_paths: set[tuple[str, ...]] = set()

    while queue and len(paths) < limit:
        current_id, node_ids, edges = queue.popleft()
        if len(edges) >= max_depth:
            continue
        for edge in adjacency.get(current_id, []):
            next_id = edge.to_entity_id
            if next_id in node_ids:
                continue
            next_nodes = node_ids + (next_id,)
            next_edges = edges + (edge,)
            if next_id in target_ids:
                if next_nodes in seen_paths:
                    continue
                seen_paths.add(next_nodes)
                paths.append(Path(nodes=next_nodes, edges=next_edges))
                if len(paths) >= limit:
                    break
            else:
                queue.append((next_id, next_nodes, next_edges))
    return paths


def path_to_dict(snapshot: Any, path: Path) -> JsonObject:
    return {
        "depth": path.depth,
        "nodes": [_entity_ref(snapshot.entities_by_id[entity_id]) for entity_id in path.nodes],
        "edges": [_edge_to_dict(snapshot, edge) for edge in path.edges],
    }


def _adjacency(snapshot: Any) -> dict[str, list[Edge]]:
    cached = getattr(snapshot, _ADJACENCY_CACHE_ATTR, None)
    if cached is not None:
        return cached
    adjacency = _build_adjacency(snapshot)
    setattr(snapshot, _ADJACENCY_CACHE_ATTR, adjacency)
    return adjacency


def _build_adjacency(snapshot: Any) -> dict[str, list[Edge]]:
    adjacency: dict[str, list[Edge]] = defaultdict(list)
    for fact in aggregations._canonical_facts(snapshot.facts):
        source = snapshot.entities_by_id.get(fact["subject_id"])
        target = snapshot.entities_by_id.get(fact["object_id"])
        if not source or not target:
            continue
        if not aggregations._is_canonical_entity(source) or not aggregations._is_canonical_entity(target):
            continue
        if not _is_allowed_edge(fact["predicate"], source["kind"], target["kind"]):
            continue
        adjacency[source["entity_id"]].append(
            Edge(
                fact_id=fact["fact_id"],
                predicate=fact["predicate"],
                direction="forward",
                to_entity_id=target["entity_id"],
                qualifier=fact.get("qualifier", {}),
            )
        )
    for edges in adjacency.values():
        edges.sort(key=lambda edge: (edge.predicate, _display(snapshot.entities_by_id[edge.to_entity_id]), edge.fact_id))
    return adjacency


def _is_allowed_edge(predicate: str, subject_kind: str, object_kind: str) -> bool:
    return (
        (
            predicate == "CALLS"
            and subject_kind == "CodeSymbol"
            and object_kind in {"CodeSymbol", "ExternalPackage", "CodeModule"}
        )
        or (predicate == "DEFINED_IN" and subject_kind == "CodeSymbol" and object_kind == "CodeModule")
        or (predicate == "IMPORTS" and subject_kind == "CodeModule" and object_kind in {"ExternalPackage", "CodeModule"})
    )


def _target_entity_ids(target_resolution: JsonObject) -> set[str]:
    if target_resolution.get("status") != "resolved":
        return set()
    target = target_resolution.get("resolved_target")
    if not target:
        return set()
    return {str(target["entity_id"])}


def _edge_to_dict(snapshot: Any, edge: Edge) -> JsonObject:
    evidence_rows = snapshot.evidence_by_target.get(edge.fact_id, [])
    source_systems = {str(row.get("source_system")) for row in evidence_rows if row.get("source_system")}
    return {
        "fact_id": edge.fact_id,
        "predicate": edge.predicate,
        "direction": edge.direction,
        "qualifier": edge.qualifier,
        "derivation_class": aggregations._strongest_derivation(evidence_rows),
        "sources_count": len(source_systems),
        "evidence_samples": [aggregations._evidence_sample(row) for row in evidence_rows[:3]],
    }


def _entity_ref(entity: JsonObject) -> JsonObject:
    return {
        "entity_id": entity["entity_id"],
        "kind": entity["kind"],
        "display_name": _display(entity),
    }


def _display(entity: JsonObject) -> str:
    identity = entity["identity"]
    if entity["kind"] == "CodeSymbol":
        return f"{identity.get('module')}.{identity.get('qualname')}"
    if entity["kind"] == "CodeModule":
        return str(identity.get("module"))
    return str(identity.get("name") or identity.get("slug") or identity)
