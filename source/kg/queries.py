from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from source.kg.models import JsonObject
from source.kg.store import read_jsonl


class KgSnapshot:
    def __init__(self, snapshot_dir: str | Path) -> None:
        root = Path(snapshot_dir).expanduser().resolve()
        self.entities = read_jsonl(root / "entities.jsonl")
        self.facts = read_jsonl(root / "facts.jsonl")
        self.evidence = read_jsonl(root / "evidence.jsonl")
        self.coverage = read_jsonl(root / "coverage.jsonl")
        self.entities_by_id = {entity["entity_id"]: entity for entity in self.entities}
        self.evidence_by_target = defaultdict(list)
        for row in self.evidence:
            self.evidence_by_target[row["target_id"]].append(row)

    def summary(self) -> JsonObject:
        by_kind: dict[str, int] = defaultdict(int)
        by_predicate: dict[str, int] = defaultdict(int)
        for entity in self.entities:
            by_kind[entity["kind"]] += 1
        for fact in self.facts:
            by_predicate[fact["predicate"]] += 1
        return {
            "entity_kinds": dict(sorted(by_kind.items())),
            "predicates": dict(sorted(by_predicate.items())),
            "coverage": self.coverage,
        }

    def find_callers(self, symbol_query: str, limit: int = 25) -> list[JsonObject]:
        targets = self._matching_symbols(symbol_query)
        target_ids = {target["entity_id"] for target in targets}
        results: list[JsonObject] = []
        for fact in self.facts:
            if fact["predicate"] != "CALLS" or fact["object_id"] not in target_ids:
                continue
            caller = self.entities_by_id.get(fact["subject_id"])
            callee = self.entities_by_id.get(fact["object_id"])
            if caller and callee:
                results.append(self._fact_result(fact, caller, callee))
                if len(results) >= limit:
                    return results
        return results

    def blast_radius(self, symbol_query: str, depth: int = 2, limit: int = 25) -> list[JsonObject]:
        roots = self._matching_symbols(symbol_query)
        graph: dict[str, list[JsonObject]] = defaultdict(list)
        for fact in self.facts:
            if fact["predicate"] == "CALLS":
                graph[fact["subject_id"]].append(fact)

        seen = {root["entity_id"] for root in roots}
        queue = deque((root["entity_id"], 0) for root in roots)
        results: list[JsonObject] = []
        while queue:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for fact in graph.get(current_id, []):
                callee = self.entities_by_id.get(fact["object_id"])
                caller = self.entities_by_id.get(fact["subject_id"])
                if not caller or not callee:
                    continue
                results.append(self._fact_result(fact, caller, callee, depth=current_depth + 1))
                if len(results) >= limit:
                    return results
                if callee["entity_id"] not in seen:
                    seen.add(callee["entity_id"])
                    queue.append((callee["entity_id"], current_depth + 1))
        return results

    def modules_importing(self, package_name: str, limit: int = 25) -> list[JsonObject]:
        results: list[JsonObject] = []
        for fact in self.facts:
            if fact["predicate"] != "IMPORTS":
                continue
            package = self.entities_by_id.get(fact["object_id"])
            module = self.entities_by_id.get(fact["subject_id"])
            if not package or not module:
                continue
            if self._import_matches(fact, package, package_name):
                results.append(self._fact_result(fact, module, package))
                if len(results) >= limit:
                    return results
        return results

    def top_dependencies(self, limit: int = 25, exclude_stdlib: bool = True, exclude_unknown: bool = True) -> list[JsonObject]:
        counts: dict[str, JsonObject] = {}
        for fact in self.facts:
            if fact["predicate"] != "IMPORTS":
                continue
            qualifier = fact.get("qualifier", {})
            category = qualifier.get("category")
            if exclude_stdlib and category in {"stdlib", "node_builtin"}:
                continue
            if exclude_unknown and category == "unknown":
                continue
            package = self.entities_by_id.get(fact["object_id"])
            if not package or package["kind"] != "ExternalPackage":
                continue
            name = str(package["identity"].get("name"))
            row = counts.setdefault(
                name,
                {
                    "name": name,
                    "category": category,
                    "import_root": qualifier.get("import_root"),
                    "distribution_name": qualifier.get("distribution_name"),
                    "importer_count": 0,
                    "sample_evidence": [],
                },
            )
            row["importer_count"] += 1
            if len(row["sample_evidence"]) < 3:
                row["sample_evidence"].extend(self.evidence_by_target.get(fact["fact_id"], [])[:1])
        return sorted(counts.values(), key=lambda row: (-row["importer_count"], row["name"]))[:limit]

    def dependency_info(self, package_name: str) -> list[JsonObject]:
        seen: dict[str, JsonObject] = {}
        for fact in self.facts:
            if fact["predicate"] != "IMPORTS":
                continue
            package = self.entities_by_id.get(fact["object_id"])
            if not package or not self._import_matches(fact, package, package_name):
                continue
            qualifier = fact.get("qualifier", {})
            name = str(package["identity"].get("name"))
            seen[name] = {
                "name": name,
                "kind": package["kind"],
                "category": qualifier.get("category"),
                "import_root": qualifier.get("import_root"),
                "distribution_name": qualifier.get("distribution_name"),
            }
        return sorted(seen.values(), key=lambda row: row["name"])

    def _matching_symbols(self, symbol_query: str) -> list[JsonObject]:
        needle = symbol_query.lower()
        return [
            entity
            for entity in self.entities
            if entity["kind"] == "CodeSymbol"
            and needle in f"{entity['identity'].get('module', '')}.{entity['identity'].get('qualname', '')}".lower()
        ]

    def _import_matches(self, fact: JsonObject, package: JsonObject, package_name: str) -> bool:
        needle = package_name.lower()
        qualifier = fact.get("qualifier", {})
        candidates = {
            str(package["identity"].get("name", "")),
            str(qualifier.get("raw_import", "")),
            str(qualifier.get("import_root", "")),
            str(qualifier.get("distribution_name", "")),
            str(qualifier.get("module_name", "")),
        }
        return needle in {candidate.lower() for candidate in candidates if candidate}

    def _fact_result(self, fact: JsonObject, subject: JsonObject, object_: JsonObject, **extra: Any) -> JsonObject:
        return {
            **extra,
            "fact_id": fact["fact_id"],
            "predicate": fact["predicate"],
            "subject": self._display(subject),
            "object": self._display(object_),
            "qualifier": fact.get("qualifier", {}),
            "evidence": self.evidence_by_target.get(fact["fact_id"], []),
        }

    def _display(self, entity: JsonObject) -> str:
        identity = entity["identity"]
        if entity["kind"] == "CodeSymbol":
            return f"{identity.get('module')}.{identity.get('qualname')}"
        if entity["kind"] == "CodeModule":
            return str(identity.get("module"))
        return str(identity.get("name") or identity.get("slug") or identity)
