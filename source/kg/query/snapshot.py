from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.core.store import read_jsonl

from . import aggregations, path_search


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

    def dependency_path(
        self,
        source_query: str,
        target_query: str,
        path: str | None = None,
        line: int | None = None,
        include_all: bool = False,
        max_depth: int = 4,
        limit: int = 5,
    ) -> JsonObject:
        max_depth = min(max(1, max_depth), 6)
        limit = min(max(1, limit), 25)
        source_resolution = self._resolve_symbol(source_query, limit=limit, path=path, line=line)
        if source_resolution["status"] == "not_found":
            return self._dependency_path_response(
                "not_found",
                source_resolution,
                None,
                max_depth=max_depth,
                limit=limit,
                paths=[],
            )
        if source_resolution["status"] == "ambiguous" and not include_all:
            return self._dependency_path_response(
                "ambiguous",
                source_resolution,
                None,
                max_depth=max_depth,
                limit=limit,
                paths=[],
            )

        if include_all:
            source_ids = {candidate["symbol_id"] for candidate in source_resolution["candidates"]}
        else:
            source_ids = {source_resolution["resolved_symbol"]["symbol_id"]}

        target_resolution = aggregations.resolve_import_target(target_query, self.facts, self.entities_by_id)
        if target_resolution["status"] != "resolved":
            return self._dependency_path_response(
                target_resolution["status"],
                source_resolution,
                target_resolution,
                max_depth=max_depth,
                limit=limit,
                paths=[],
            )

        paths = path_search.find_dependency_paths(
            self,
            source_ids,
            target_resolution,
            max_depth=max_depth,
            limit=limit,
        )
        return self._dependency_path_response(
            "resolved" if paths else "empty",
            source_resolution,
            target_resolution,
            max_depth=max_depth,
            limit=limit,
            paths=[path_search.path_to_dict(self, result_path) for result_path in paths],
        )

    def cross_repo_links(self, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit)
        links = []
        for fact in self.facts:
            if fact["predicate"] not in {"RESOLVES_TO_REPO", "RESOLVES_TO_SERVICE"}:
                continue
            package = self.entities_by_id.get(fact["subject_id"])
            target = self.entities_by_id.get(fact["object_id"])
            if not package or not target:
                continue
            links.append(self._fact_result(fact, package, target))
        links = sorted(
            links,
            key=lambda row: (
                str(row.get("qualifier", {}).get("consumer_repo", "")),
                str(row.get("qualifier", {}).get("package_name", "")),
                row["predicate"],
            ),
        )
        returned = links[:limit]
        return {
            "status": "found" if links else "not_found",
            "link_count": len(links),
            "returned_count": len(returned),
            "links": returned,
        }

    def repo_dependencies(self, repo: str, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit)
        links = []
        for fact in self.facts:
            if fact["predicate"] != "RESOLVES_TO_REPO":
                continue
            package = self.entities_by_id.get(fact["subject_id"])
            target_repo = self.entities_by_id.get(fact["object_id"])
            if not package or not target_repo:
                continue
            qualifier = fact.get("qualifier", {})
            if qualifier.get("consumer_repo") != repo:
                continue
            links.append(self._fact_result(fact, package, target_repo))
        links = sorted(
            links,
            key=lambda row: (
                str(row.get("object")),
                str(row.get("qualifier", {}).get("package_name", "")),
            ),
        )
        returned = links[:limit]
        return {
            "status": "found" if links else "not_found",
            "repo": repo,
            "dependency_count": len(links),
            "returned_count": len(returned),
            "dependencies": returned,
        }

    def domain_references(self, domain_query: str, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit, max_limit=100)
        domains = [
            entity
            for entity in self.entities
            if entity["kind"] == "Domain" and domain_query.lower() in str(entity["identity"].get("name", "")).lower()
        ]
        domain_ids = {entity["entity_id"] for entity in domains}
        references = []
        env_var_ids = set()
        for fact in self.facts:
            if fact["predicate"] not in {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"}:
                continue
            if fact["subject_id"] not in domain_ids and fact["object_id"] not in domain_ids:
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            object_ = self.entities_by_id.get(fact["object_id"])
            if not subject or not object_:
                continue
            references.append(self._fact_result(fact, subject, object_))
            if fact["predicate"] == "REFERENCES_DOMAIN" and subject.get("kind") == "EnvVar":
                env_var_ids.add(subject["entity_id"])
        for fact in self.facts:
            if fact["predicate"] != "REFERENCES_ENV_VAR" or fact["object_id"] not in env_var_ids:
                continue
            qualifier = fact.get("qualifier", {})
            if not isinstance(qualifier, dict) or qualifier.get("reference_kind") != "code_access":
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            object_ = self.entities_by_id.get(fact["object_id"])
            if subject and object_:
                references.append(self._fact_result(fact, subject, object_))
        references = _dedupe_fact_results(references)
        references = sorted(references, key=lambda row: (str(row.get("object")), str(row.get("subject"))))
        returned = references[:limit]
        return {
            "status": "found" if references else "not_found",
            "query": domain_query,
            "domain_count": len(domain_ids),
            "reference_count": len(references),
            "returned_count": len(returned),
            "references": returned,
        }

    def endpoints(self, path_query: str | None = None, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit, max_limit=100)
        rows = []
        for fact in self.facts:
            if fact["predicate"] not in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}:
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            endpoint = self.entities_by_id.get(fact["object_id"])
            if not subject or not endpoint or endpoint.get("kind") != "Endpoint":
                continue
            path = str(endpoint.get("identity", {}).get("path", ""))
            if path_query and path_query.lower() not in path.lower():
                continue
            rows.append(self._fact_result(fact, subject, endpoint))
        rows = sorted(
            rows,
            key=lambda row: (
                str(row["qualifier"].get("path", "")),
                str(row.get("predicate", "")),
                str(row.get("object", "")),
            ),
        )
        returned = rows[:limit]
        return {
            "status": "found" if rows else "not_found",
            "query": path_query,
            "endpoint_fact_count": len(rows),
            "returned_count": len(returned),
            "endpoints": returned,
        }

    def reconcile_endpoints(
        self,
        docs_scope: list[str] | tuple[str, ...] = (),
        backend_scope: list[str] | tuple[str, ...] = (),
        client_scope: list[str] | tuple[str, ...] = (),
        path_prefix: str | None = None,
    ) -> JsonObject:
        from source.kg.product.contract_reconciliation import ContractReconciliationSpec, ContractSide, reconcile_contract

        docs_vs_backend = reconcile_contract(
            self,
            ContractReconciliationSpec(
                name="docs_vs_backend_endpoints",
                identity_key="endpoint_path",
                left=ContractSide(
                    name="documented",
                    predicates=("DOCUMENTS_ENDPOINT",),
                    repos=tuple(docs_scope),
                    path_prefix=path_prefix,
                ),
                right=ContractSide(
                    name="implemented",
                    predicates=("EXPOSES_ENDPOINT",),
                    repos=tuple(backend_scope),
                    path_prefix=path_prefix,
                ),
            ),
        )
        docs_vs_client = reconcile_contract(
            self,
            ContractReconciliationSpec(
                name="docs_vs_client_endpoints",
                identity_key="endpoint_path",
                left=ContractSide(
                    name="documented",
                    predicates=("DOCUMENTS_ENDPOINT",),
                    repos=tuple(docs_scope),
                    path_prefix=path_prefix,
                ),
                right=ContractSide(
                    name="called",
                    predicates=("CALLS_ENDPOINT",),
                    repos=tuple(client_scope),
                    path_prefix=path_prefix,
                ),
            ),
        )
        return {
            "status": "found" if docs_vs_backend["status"] == "found" or docs_vs_client["status"] == "found" else "not_found",
            "docs_scope": list(docs_scope),
            "backend_scope": list(backend_scope),
            "client_scope": list(client_scope),
            "path_prefix": path_prefix,
            "documented_AND_implemented": docs_vs_backend["matched"],
            "documented_NOT_implemented": docs_vs_backend["left_only"],
            "implemented_NOT_documented": docs_vs_backend["right_only"],
            "documented_AND_called": docs_vs_client["matched"],
            "documented_NOT_called": docs_vs_client["left_only"],
            "coverage_warnings": self._endpoint_reconciliation_warnings(docs_scope, backend_scope, client_scope, path_prefix),
        }

    def event_channels(self, channel_query: str | None = None, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit, max_limit=100)
        rows = []
        for fact in self.facts:
            if fact["predicate"] not in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}:
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            channel = self.entities_by_id.get(fact["object_id"])
            if not subject or not channel or channel.get("kind") != "EventChannel":
                continue
            identity = channel.get("identity", {})
            name = str(identity.get("channel_address") or identity.get("name") or "")
            if channel_query and channel_query.lower() not in name.lower():
                continue
            rows.append(self._fact_result(fact, subject, channel))
        rows = sorted(
            rows,
            key=lambda row: (
                str(row["qualifier"].get("path", "")),
                str(row.get("predicate", "")),
                str(row.get("object", "")),
            ),
        )
        returned = rows[:limit]
        return {
            "status": "found" if rows else "not_found",
            "query": channel_query,
            "event_fact_count": len(rows),
            "returned_count": len(returned),
            "event_channels": returned,
        }

    def _endpoint_reconciliation_warnings(
        self,
        docs_scope: list[str] | tuple[str, ...],
        backend_scope: list[str] | tuple[str, ...],
        client_scope: list[str] | tuple[str, ...],
        path_prefix: str | None,
    ) -> list[JsonObject]:
        warnings: list[JsonObject] = []
        if docs_scope and not self._has_endpoint_fact("DOCUMENTS_ENDPOINT", docs_scope, path_prefix):
            warnings.append(
                {
                    "scope": "docs",
                    "warning": "no_endpoint_documentation_evidence",
                    "coverage": self._endpoint_coverage_rows("DOCUMENTS_ENDPOINT", docs_scope),
                }
            )
        if backend_scope and not self._has_endpoint_fact("EXPOSES_ENDPOINT", backend_scope, path_prefix):
            warnings.append(
                {
                    "scope": "backend",
                    "warning": "no_endpoint_extractor_matched",
                    "coverage": self._endpoint_coverage_rows("EXPOSES_ENDPOINT", backend_scope),
                }
            )
        if client_scope and not self._has_endpoint_fact("CALLS_ENDPOINT", client_scope, path_prefix):
            warnings.append(
                {
                    "scope": "client",
                    "warning": "no_client_call_evidence",
                    "coverage": self._endpoint_coverage_rows("CALLS_ENDPOINT", client_scope),
                }
            )
        return warnings

    def _has_endpoint_fact(self, predicate: str, repos: list[str] | tuple[str, ...], path_prefix: str | None = None) -> bool:
        repo_filter = set(repos)
        for fact in self.facts:
            if fact.get("predicate") != predicate:
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            object_ = self.entities_by_id.get(fact["object_id"])
            if not subject or not object_:
                continue
            if path_prefix and not self._endpoint_path_matches(object_, path_prefix):
                continue
            if self._entity_repo(subject) in repo_filter or self._entity_repo(object_) in repo_filter:
                return True
        return False

    def _endpoint_coverage_rows(
        self,
        predicate: str,
        repos: list[str] | tuple[str, ...],
    ) -> list[JsonObject]:
        repo_filter = set(repos)
        return [
            row
            for row in self.coverage
            if row.get("predicate") == predicate and str(row.get("scope_ref", {}).get("repo")) in repo_filter
        ]

    def _endpoint_path_matches(self, entity: JsonObject, path_prefix: str) -> bool:
        if entity.get("kind") != "Endpoint":
            return False
        path = self._normalize_endpoint_reconciliation_path(str(entity.get("identity", {}).get("path", "")))
        return path.startswith(path_prefix)

    def _normalize_endpoint_reconciliation_path(self, path: str) -> str:
        value = path.strip()
        if not value.startswith("/"):
            value = "/" + value
        return value.rstrip("/") or "/"

    def _entity_repo(self, entity: JsonObject) -> str | None:
        identity = entity.get("identity", {})
        properties = entity.get("properties", {})
        return identity.get("repo") or properties.get("repo")

    def deploy_mappings(self, target_query: str | None = None, limit: int = 25) -> JsonObject:
        limit = self._clamp_limit(limit, max_limit=100)
        rows = []
        for fact in self.facts:
            if fact["predicate"] != "ROUTES_DOMAIN_TO_DEPLOY":
                continue
            subject = self.entities_by_id.get(fact["subject_id"])
            target = self.entities_by_id.get(fact["object_id"])
            if not subject or not target:
                continue
            haystack = f"{self._display(subject)} {self._display(target)} {fact.get('qualifier', {})}".lower()
            if target_query and target_query.lower() not in haystack:
                continue
            rows.append(self._fact_result(fact, subject, target))
        rows = sorted(rows, key=lambda row: (str(row.get("subject")), str(row.get("object"))))
        returned = rows[:limit]
        return {
            "status": "found" if rows else "not_found",
            "query": target_query,
            "mapping_count": len(rows),
            "returned_count": len(returned),
            "mappings": returned,
        }

    def _clamp_limit(self, limit: int, max_limit: int = 100) -> int:
        return min(max(1, limit), max_limit)

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

    def _dependency_path_response(
        self,
        status: str,
        source_resolution: JsonObject,
        target_resolution: JsonObject | None,
        max_depth: int,
        limit: int,
        paths: list[JsonObject],
    ) -> JsonObject:
        response: JsonObject = {
            "status": status,
            "source": source_resolution,
            "max_depth": max_depth,
            "limit": limit,
            "path_count": len(paths),
            "returned_count": len(paths),
            "paths": paths,
        }
        if target_resolution is not None:
            response["target"] = target_resolution
        return response

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
        return display_entity(entity)


def _dedupe_fact_results(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        fact_id = row.get("fact_id")
        if fact_id in seen:
            continue
        seen.add(fact_id)
        deduped.append(row)
    return deduped
