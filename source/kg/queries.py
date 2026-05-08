from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from source.kg import aggregations
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

    def find_callers(
        self,
        symbol_query: str,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
        include_all: bool = False,
    ) -> JsonObject:
        resolution = self._resolve_symbol(symbol_query, limit=limit, path=path, line=line)
        if resolution["status"] == "not_found":
            return {"status": "not_found", "target": resolution, "callers": []}
        if resolution["status"] == "ambiguous" and not include_all:
            return {"status": "ambiguous", "target": resolution, "callers": []}

        if include_all:
            target_ids = {candidate["symbol_id"] for candidate in resolution["candidates"]}
        else:
            target_ids = {resolution["resolved_symbol"]["symbol_id"]}
        results: list[JsonObject] = []
        for fact in self.facts:
            if fact["predicate"] != "CALLS" or fact["object_id"] not in target_ids:
                continue
            caller = self.entities_by_id.get(fact["subject_id"])
            callee = self.entities_by_id.get(fact["object_id"])
            if caller and callee:
                results.append(self._fact_result(fact, caller, callee))
                if len(results) >= limit:
                    break
        return {
            "status": "found" if results else "not_found",
            "target": resolution,
            "caller_count": len(results),
            "callers": results,
        }

    def find_callees(
        self,
        symbol_query: str,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
        include_all: bool = False,
    ) -> JsonObject:
        resolution = self._resolve_symbol(symbol_query, limit=limit, path=path, line=line)
        if resolution["status"] == "not_found":
            return {"status": "not_found", "source": resolution, "callees": []}
        if resolution["status"] == "ambiguous" and not include_all:
            return {"status": "ambiguous", "source": resolution, "callees": []}

        if include_all:
            source_ids = {candidate["symbol_id"] for candidate in resolution["candidates"]}
        else:
            source_ids = {resolution["resolved_symbol"]["symbol_id"]}
        results: list[JsonObject] = []
        for fact in self.facts:
            if fact["predicate"] != "CALLS" or fact["subject_id"] not in source_ids:
                continue
            caller = self.entities_by_id.get(fact["subject_id"])
            callee = self.entities_by_id.get(fact["object_id"])
            if caller and callee:
                results.append(self._fact_result(fact, caller, callee))
                if len(results) >= limit:
                    break
        return {
            "status": "found" if results else "not_found",
            "source": resolution,
            "callee_count": len(results),
            "callees": results,
        }

    def blast_radius(
        self,
        symbol_query: str,
        depth: int = 2,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
        include_all: bool = False,
    ) -> JsonObject:
        resolution = self._resolve_symbol(symbol_query, limit=limit, path=path, line=line)
        if resolution["status"] == "not_found":
            return {"status": "not_found", "source": resolution, "edges": []}
        if resolution["status"] == "ambiguous" and not include_all:
            return {"status": "ambiguous", "source": resolution, "edges": []}

        if include_all:
            root_ids = {candidate["symbol_id"] for candidate in resolution["candidates"]}
        else:
            root_ids = {resolution["resolved_symbol"]["symbol_id"]}
        graph: dict[str, list[JsonObject]] = defaultdict(list)
        for fact in self.facts:
            if fact["predicate"] == "CALLS":
                graph[fact["subject_id"]].append(fact)

        seen = set(root_ids)
        queue = deque((root_id, 0) for root_id in root_ids)
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
                    return {
                        "status": "found",
                        "source": resolution,
                        "depth": depth,
                        "edge_count": len(results),
                        "edges": results,
                    }
                if callee["entity_id"] not in seen:
                    seen.add(callee["entity_id"])
                    queue.append((callee["entity_id"], current_depth + 1))
        return {
            "status": "found" if results else "not_found",
            "source": resolution,
            "depth": depth,
            "edge_count": len(results),
            "edges": results,
        }

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

    def who_imports(
        self,
        target: str,
        group_prefix_depth: int = 2,
        no_grouping: bool = False,
        limit: int = 25,
    ) -> JsonObject:
        return aggregations.who_imports(
            target=target,
            entities_by_id=self.entities_by_id,
            facts=self.facts,
            evidence_by_target=self.evidence_by_target,
            group_prefix_depth=group_prefix_depth,
            no_grouping=no_grouping,
            limit=limit,
        )

    def top_internal_dependencies(self, relative_only: bool = False, limit: int = 25) -> JsonObject:
        return aggregations.top_internal_dependencies(
            entities_by_id=self.entities_by_id,
            facts=self.facts,
            evidence_by_target=self.evidence_by_target,
            relative_only=relative_only,
            limit=limit,
        )

    def top_fan_in_symbols(self, include_external: bool = False, limit: int = 25) -> JsonObject:
        return aggregations.top_fan_in_symbols(
            entities_by_id=self.entities_by_id,
            facts=self.facts,
            evidence_by_target=self.evidence_by_target,
            include_external=include_external,
            limit=limit,
        )

    def modules_importing_both(
        self,
        left: str,
        right: str,
        category_filter: set[str] | None = None,
        limit: int = 25,
    ) -> JsonObject:
        return aggregations.modules_importing_both(
            left=left,
            right=right,
            entities_by_id=self.entities_by_id,
            facts=self.facts,
            evidence_by_target=self.evidence_by_target,
            category_filter=category_filter,
            limit=limit,
        )

    def lookup_symbol(
        self,
        symbol_query: str,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
    ) -> JsonObject:
        return self._resolve_symbol(symbol_query, limit=limit, path=path, line=line)

    def symbols_in_file(self, file_path: str, limit: int = 100) -> JsonObject:
        normalized_path = self._normalize_path(file_path)
        symbols = sorted(
            [
                self._symbol_result(entity)
                for entity in self._symbol_entities()
                if self._normalize_path(str(entity.get("properties", {}).get("path", ""))) == normalized_path
            ],
            key=lambda row: (row.get("line") or 0, row["display_name"]),
        )
        returned_symbols = symbols[:limit]
        return {
            "status": "found" if symbols else "not_found",
            "path": normalized_path,
            "symbol_count": len(symbols),
            "returned_count": len(returned_symbols),
            "symbols": returned_symbols,
        }

    def evidence_for_call(
        self,
        caller_query: str,
        callee_query: str,
        path: str | None = None,
        line: int | None = None,
        limit: int = 25,
    ) -> JsonObject:
        caller_resolution = self._resolve_symbol(caller_query, limit=limit, path=path, line=line)
        if caller_resolution["status"] != "resolved":
            return {
                "status": "ambiguous" if caller_resolution["status"] == "ambiguous" else "not_found",
                "caller": caller_resolution,
                "callee": self._resolve_symbol(callee_query, limit=limit),
                "matches": [],
            }

        caller_id = caller_resolution["resolved_symbol"]["symbol_id"]
        coordinate_matches = self._call_facts_at_coordinate(caller_id, callee_query, path=path, line=line)
        if path or line is not None:
            return self._call_evidence_result(
                caller_resolution=caller_resolution,
                callee_query=callee_query,
                facts=coordinate_matches,
                limit=limit,
                path=path,
                line=line,
            )

        callee_resolution = self._resolve_symbol(callee_query, limit=limit)
        if callee_resolution["status"] != "resolved":
            return {
                "status": "ambiguous" if callee_resolution["status"] == "ambiguous" else "not_found",
                "caller": caller_resolution,
                "callee": callee_resolution,
                "matches": [],
            }

        callee_id = callee_resolution["resolved_symbol"]["symbol_id"]
        facts = [
            fact
            for fact in self.facts
            if fact["predicate"] == "CALLS" and fact["subject_id"] == caller_id and fact["object_id"] == callee_id
        ]
        return self._call_evidence_result(
            caller_resolution=caller_resolution,
            callee_query=callee_query,
            facts=facts,
            limit=limit,
            path=path,
            line=line,
            callee_resolution=callee_resolution,
        )

    def _call_evidence_result(
        self,
        caller_resolution: JsonObject,
        callee_query: str,
        facts: list[JsonObject],
        limit: int,
        path: str | None,
        line: int | None,
        callee_resolution: JsonObject | None = None,
    ) -> JsonObject:
        matches: list[JsonObject] = []
        callee_entities: dict[str, JsonObject] = {}
        for fact in facts:
            evidence_rows = self.evidence_by_target.get(fact["fact_id"], [])
            if path or line is not None:
                evidence_rows = [
                    row
                    for row in evidence_rows
                    if self._evidence_matches_coordinate(row, path=path, line=line)
                ]
            if not evidence_rows:
                continue
            caller = self.entities_by_id.get(fact["subject_id"])
            callee = self.entities_by_id.get(fact["object_id"])
            if caller and callee:
                callee_entities[callee["entity_id"]] = callee
                matches.append({**self._fact_result(fact, caller, callee), "evidence": evidence_rows})
                if len(matches) >= limit:
                    break
        callee_resolution = callee_resolution or self._callee_resolution_from_matches(callee_query, list(callee_entities.values()), limit)
        return {
            "status": "found" if matches else "not_found",
            "caller": caller_resolution,
            "callee": callee_resolution,
            "matches": matches,
        }

    def _call_facts_at_coordinate(
        self,
        caller_id: str,
        callee_query: str,
        path: str | None,
        line: int | None,
    ) -> list[JsonObject]:
        facts: list[JsonObject] = []
        for fact in self.facts:
            if fact["predicate"] != "CALLS" or fact["subject_id"] != caller_id:
                continue
            callee = self.entities_by_id.get(fact["object_id"])
            if not callee or not self._symbol_query_matches_entity(callee_query, callee):
                continue
            evidence_rows = self.evidence_by_target.get(fact["fact_id"], [])
            if any(self._evidence_matches_coordinate(row, path=path, line=line) for row in evidence_rows):
                facts.append(fact)
        return facts

    def _callee_resolution_from_matches(self, callee_query: str, entities: list[JsonObject], limit: int) -> JsonObject:
        if not entities:
            return self._resolve_symbol(callee_query, limit=limit)
        return self._resolution_result(callee_query, "exact_name", entities, limit)

    def _matching_symbols(self, symbol_query: str) -> list[JsonObject]:
        needle = symbol_query.lower()
        return [
            entity
            for entity in self.entities
            if entity["kind"] == "CodeSymbol"
            and needle in f"{entity['identity'].get('module', '')}.{entity['identity'].get('qualname', '')}".lower()
        ]

    def _resolve_symbol(
        self,
        symbol_query: str,
        limit: int = 25,
        path: str | None = None,
        line: int | None = None,
    ) -> JsonObject:
        query = symbol_query.strip()
        if not query:
            return {
                "status": "not_found",
                "query": symbol_query,
                "confidence": "empty_query",
                "resolved_symbol": None,
                "candidates": [],
            }

        exact_qualified = []
        exact_name = []
        fuzzy = []
        needle = query.lower()
        query_is_qualified = "." in query
        for entity in self._symbol_entities():
            if (path or line is not None) and not self._symbol_matches_coordinate(entity, path=path, line=line):
                continue
            qualified = self._display(entity)
            qualname = str(entity["identity"].get("qualname", ""))
            short_name = qualname.rsplit(".", 1)[-1]
            if qualified.lower() == needle:
                exact_qualified.append(entity)
            elif query_is_qualified and qualname.lower() == needle:
                exact_name.append(entity)
            elif not query_is_qualified and (qualname.lower() == needle or short_name.lower() == needle):
                exact_name.append(entity)
            elif needle in qualified.lower():
                fuzzy.append(entity)

        if exact_qualified:
            return self._resolution_result(query, "exact_qualified", exact_qualified, limit)
        if exact_name:
            return self._resolution_result(query, "exact_name", exact_name, limit)
        if fuzzy:
            return self._resolution_result(query, "fuzzy", fuzzy, limit)
        return {
            "status": "not_found",
            "query": query,
            "confidence": "not_found",
            "resolved_symbol": None,
            "candidates": [],
        }

    def _resolution_result(self, query: str, match_type: str, entities: list[JsonObject], limit: int) -> JsonObject:
        candidates = sorted((self._symbol_result(entity) for entity in entities), key=self._symbol_sort_key)
        is_unique = len(candidates) == 1
        confidence = {
            "exact_qualified": "exact_unique" if is_unique else "exact_multiple",
            "exact_name": "exact_unique" if is_unique else "exact_multiple",
            "fuzzy": "fuzzy_unique" if is_unique else "fuzzy_multiple",
        }[match_type]
        return {
            "status": "resolved" if is_unique else "ambiguous",
            "query": query,
            "confidence": confidence,
            "resolved_symbol": candidates[0] if is_unique else None,
            "candidates": candidates[:limit],
            "candidate_count": len(candidates),
        }

    def _symbol_entities(self) -> list[JsonObject]:
        return [entity for entity in self.entities if entity["kind"] == "CodeSymbol"]

    def _symbol_result(self, entity: JsonObject) -> JsonObject:
        identity = entity["identity"]
        properties = entity.get("properties", {})
        return {
            "symbol_id": entity["entity_id"],
            "display_name": self._display(entity),
            "qualified_name": f"{identity.get('module')}.{identity.get('qualname')}",
            "repo": identity.get("repo"),
            "module": identity.get("module"),
            "qualname": identity.get("qualname"),
            "symbol_kind": identity.get("symbol_kind"),
            "path": properties.get("path"),
            "line": properties.get("line"),
            "end_line": properties.get("end_line"),
            "evidence": self.evidence_by_target.get(entity["entity_id"], []),
        }

    def _symbol_sort_key(self, row: JsonObject) -> tuple[str, int, str]:
        return (str(row.get("path") or ""), int(row.get("line") or 0), row["display_name"])

    def _evidence_matches_coordinate(self, evidence: JsonObject, path: str | None, line: int | None) -> bool:
        bytes_ref = evidence.get("bytes_ref") or {}
        if path and self._normalize_path(str(bytes_ref.get("path", ""))) != self._normalize_path(path):
            return False
        if line is None:
            return True
        line_start = int(bytes_ref.get("line_start") or 0)
        line_end = int(bytes_ref.get("line_end") or line_start)
        return line_start <= line <= line_end

    def _symbol_matches_coordinate(self, entity: JsonObject, path: str | None, line: int | None) -> bool:
        properties = entity.get("properties", {})
        if path and self._normalize_path(str(properties.get("path", ""))) != self._normalize_path(path):
            return False
        if line is None:
            return True

        start = properties.get("line")
        end = properties.get("end_line")
        if start is not None:
            line_start = int(start)
            line_end = int(end or start)
            if line_start <= line <= line_end:
                return True
        return any(
            self._evidence_matches_coordinate(row, path=path, line=line)
            for row in self.evidence_by_target.get(entity["entity_id"], [])
        )

    def _symbol_query_matches_entity(self, symbol_query: str, entity: JsonObject) -> bool:
        if entity["kind"] != "CodeSymbol":
            return False
        query = symbol_query.strip().lower()
        identity = entity["identity"]
        qualified = self._display(entity).lower()
        qualname = str(identity.get("qualname", "")).lower()
        short_name = qualname.rsplit(".", 1)[-1]
        if "." in query:
            return query in {qualified, qualname}
        return query in {qualname, short_name}

    def _normalize_path(self, file_path: str) -> str:
        return file_path.replace("\\", "/").lstrip("./")

    def _import_matches(self, fact: JsonObject, package: JsonObject, package_name: str) -> bool:
        return aggregations.import_matches_target(fact, package, package_name)

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
