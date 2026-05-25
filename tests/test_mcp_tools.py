from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.product.mcp_tools import TOOL_NAMES, _planning_context_symbol_impact, call_tool, tool_definitions
from source.kg.query.snapshot import KgSnapshot
from source.scripts.mcp_server import (
    _JsonPayloadError,
    MCP_PROTOCOL_VERSION,
    REQUEST_READ_TIMEOUT_SECONDS,
    _content_length,
    _decode_json_payload,
    _format_host_for_url,
    _handler_class,
    _handle_json_rpc,
    _handle_json_rpc_payload,
    _is_loopback_host,
    _read_request_body,
    _RequestBodyTimeout,
    _server_address_for_host,
    _server_class_for_host,
)


EXTENSION_TOOL_NAMES: tuple[str, ...] = ("planning_context", "review_context")


def _assert_additive_fields(testcase: unittest.TestCase, payload: dict[str, object]) -> None:
    testcase.assertIn("coverage_warnings", payload)
    testcase.assertIn("unsupported_scopes", payload)
    testcase.assertIn("next_actions", payload)
    testcase.assertIsInstance(payload["coverage_warnings"], list)
    testcase.assertIsInstance(payload["unsupported_scopes"], list)
    testcase.assertIsInstance(payload["next_actions"], list)


class McpToolsTest(unittest.TestCase):
    def test_tool_definitions_include_adr_names_and_workflow_extensions(self) -> None:
        definitions = tool_definitions()
        self.assertEqual([row["name"] for row in definitions], [*TOOL_NAMES, *EXTENSION_TOOL_NAMES])
        schemas = {row["name"]: row["inputSchema"] for row in definitions}
        descriptions = {row["name"]: row["description"] for row in definitions}
        self.assertEqual(schemas["search_services"]["properties"]["query"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["path"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["line"]["type"], ["integer", "null"])
        self.assertEqual(schemas["planning_context"]["properties"]["symbol"]["type"], ["string", "null"])
        self.assertEqual(schemas["review_context"]["properties"]["changed_files"]["type"], "array")
        self.assertNotIn("depth", schemas["review_context"]["properties"])
        self.assertIn("operational_surfaces.evidence_partition", descriptions["get_service_brief"])
        self.assertIn("service_operational_surfaces.evidence_partition", descriptions["planning_context"])
        self.assertIn("known_linked", descriptions["planning_context"])
        self.assertIn("unlinked_evidence", descriptions["planning_context"])
        self.assertIn("missing_contracts", descriptions["planning_context"])

    def test_planning_context_resolves_structured_and_query_inputs(self) -> None:
        with _fixture_snapshot() as kg:
            symbol = call_tool(kg, "planning_context", {"symbol": "charge_card"})
            query = call_tool(kg, "planning_context", {"query": "shared-lib"})

        self.assertEqual(symbol["status"], "found")
        self.assertIn("anchors", symbol)
        self.assertEqual(query["status"], "found")
        self.assertEqual(query["anchors"]["package"], "shared-lib")
        self.assertEqual(query["dependencies"][0]["predicate"], "IMPORTS")

    def test_planning_context_ambiguous_and_empty_inputs_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            ambiguous = call_tool(kg, "planning_context", {"query": "payments"})
            self.assertEqual(ambiguous["status"], "ambiguous")
            self.assertTrue(ambiguous["next_actions"])
            self.assertTrue(any(row["predicate"] == "RESOLVES_TO_REPO" for row in ambiguous["dependencies"]))
            with self.assertRaisesRegex(ValueError, "planning_context requires at least one of"):
                call_tool(kg, "planning_context", {})

    def test_planning_context_package_query_does_not_treat_limited_rows_as_unique(self) -> None:
        with _fixture_snapshot(extra_package_importers=1) as kg:
            ambiguous = call_tool(kg, "planning_context", {"query": "shared-lib", "limit": 1})

        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertTrue(ambiguous["next_actions"])
        self.assertEqual(len(ambiguous["dependencies"]), 1)
        self.assertEqual(ambiguous["dependencies"][0]["predicate"], "IMPORTS")

    def test_planning_context_raw_query_substring_matches_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            endpoint = call_tool(kg, "planning_context", {"query": "/check"})
            event_channel = call_tool(kg, "planning_context", {"query": "orders"})
            domain = call_tool(kg, "planning_context", {"query": "internal"})

        self.assertEqual(endpoint["status"], "ambiguous")
        self.assertTrue(endpoint["next_actions"])
        self.assertEqual(event_channel["status"], "ambiguous")
        self.assertTrue(event_channel["next_actions"])
        self.assertEqual(domain["status"], "ambiguous")
        self.assertTrue(domain["next_actions"])

    def test_planning_context_raw_query_zero_hits_is_ambiguous(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"query": "definitely-missing-anchor"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertTrue(result["next_actions"])

    def test_planning_context_symbol_ambiguity_returns_candidates(self) -> None:
        with _fixture_snapshot(extra_charge_card_symbol=True) as kg:
            result = call_tool(kg, "planning_context", {"symbol": "charge_card"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertGreaterEqual(len(result["symbols"]), 2)
        self.assertTrue(result["next_actions"])

    def test_planning_context_multiple_primary_anchors_intersect(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"repo": "payments", "package": "shared-lib"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["anchors"]["repo"], "payments")
        self.assertEqual(result["anchors"]["package"], "shared-lib")
        self.assertEqual({row["predicate"] for row in result["dependencies"]}, {"IMPORTS", "RESOLVES_TO_REPO"})
        self.assertEqual(result["snapshot_summary"]["entity_count"], 11)
        self.assertEqual(result["snapshot_summary"]["fact_count"], 7)
        self.assertEqual(result["snapshot_scope"]["repo"], "payments")
        self.assertGreater(result["snapshot_scope"]["entity_count"], 0)
        self.assertGreater(result["snapshot_scope"]["fact_count"], 0)

    def test_planning_context_service_and_repo_narrow_without_scope_rejection(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "repo": "payments"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")

    def test_planning_context_repo_scope_hint_does_not_promote_missing_rows(self) -> None:
        with _fixture_snapshot(extra_consumers=1) as kg:
            result = call_tool(kg, "planning_context", {"repo": "consumer-0"})

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["answerability"]["status"], "not_answerable")
        self.assertEqual(result["snapshot_scope"]["repo"], "consumer-0")
        self.assertGreater(result["snapshot_scope"]["entity_count"], 0)
        self.assertTrue(any("snapshot_summary" in action for action in result["next_actions"]))

    def test_planning_context_single_substring_service_anchor_stays_found(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "pay"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")

    def test_planning_context_symbol_path_and_line_narrow_deterministically(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"symbol": "charge_card", "path": "payments/gateway.py", "line": 5})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "charge_card")

    def test_planning_context_path_and_line_filter_before_limit(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"path": "payments/checkout.py", "line": 10, "limit": 1})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "handle_checkout")

    def test_planning_context_fact_line_filter_uses_attached_evidence(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "planning_context",
                {"package": "shared-lib", "line": 2},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual({row["predicate"] for row in result["dependencies"]}, {"IMPORTS"})

    def test_planning_context_symbol_path_and_line_disambiguate_symbol_anchor(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "planning_context",
                {"symbol": "charge_card", "path": "payments/gateway.py", "line": 5},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "charge_card")
        self.assertEqual(result["symbols"][0]["path"], "payments/gateway.py")

    def test_planning_context_repo_filters_service_anchor_without_failing_closed(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "repo": "payments"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")
        self.assertEqual({row["predicate"] for row in result["dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_planning_context_service_anchor_returns_composed_context(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "payments"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["answerability"]["status"], "answerable")
        self.assertEqual(result["answerability"]["missing_fact_families"], [])
        self.assertEqual(result["summary"]["service_count"], 1)
        self.assertEqual(result["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(result["summary"]["event_fact_count"], 1)
        self.assertTrue(any(row["section"] == "services" for row in result["entry_points"]))
        service_brief = result["related_facts"]["service_brief"]
        self.assertEqual(service_brief["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(service_brief["summary"]["event_fact_count"], 1)
        self.assertEqual(service_brief["summary"]["deploy_mapping_count"], 0)
        self.assertEqual(service_brief["summary"]["endpoint_fact_count"], result["summary"]["endpoint_fact_count"])
        self.assertEqual(service_brief["summary"]["event_fact_count"], result["summary"]["event_fact_count"])
        self.assertFalse(any(family == "deploy_mapping" for family in result["answerability"]["missing_fact_families"]))

    def test_planning_context_service_anchor_includes_endpoint_consumers(self) -> None:
        with _fixture_snapshot(endpoint_consumer=True) as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "limit": 10})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["summary"]["endpoint_consumer_fact_count"], 1)
        self.assertEqual(result["endpoint_consumers"][0]["consumer"]["slug"], "web")
        self.assertEqual(result["related_facts"]["service_brief"]["summary"]["endpoint_consumer_fact_count"], 1)
        self.assertEqual(result["related_facts"]["endpoint_consumers"][0]["matched_provider_endpoint"]["path"], "/checkout")

    def test_planning_context_includes_inventory_and_dependency_importers(self) -> None:
        with _fixture_snapshot(extra_package_importers=2) as kg:
            result = call_tool(kg, "planning_context", {"package": "shared-lib", "limit": 10})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["inventory"]["scope"], {"kind": "fleet"})
        self.assertEqual(result["related_facts"]["dependency_importers"]["summary"]["importer_fact_count"], 3)
        self.assertEqual(result["related_facts"]["dependency_importers"]["repo_counts"], {"payments": 3})
        self.assertEqual(result["related_facts"]["dependency_importers"]["packages"][0]["name"], "shared-lib")

    def test_planning_context_includes_service_operational_surfaces(self) -> None:
        with _fixture_snapshot(operational_deploy_mapping=True, operational_deploy_same_repo=True) as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "limit": 10})

        surfaces = result["service_operational_surfaces"]
        self.assertEqual(surfaces["status"], "found")
        self.assertEqual(surfaces["summary"]["deploy_target_candidate_count"], 1)
        self.assertEqual(surfaces["summary"]["domain_route_candidate_count"], 1)
        self.assertEqual(surfaces["evidence_buckets"], ["known_linked", "unlinked_evidence", "missing_contracts"])
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["status"], "found")
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["counts"]["domain_route_count"], 1)
        self.assertEqual(
            result["related_facts"]["service_operational_surfaces"]["domain_route_candidates"][0]["predicate"],
            "ROUTES_DOMAIN_TO_DEPLOY",
        )

    def test_planning_context_symbol_anchor_returns_impact_and_coordinates(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"symbol": "handle_checkout"})

        self.assertEqual(result["status"], "found")
        symbol_impact = result["related_facts"]["symbol_impact"]
        self.assertEqual(symbol_impact["status"], "found")
        self.assertEqual(symbol_impact["symbol"]["qualname"], "handle_checkout")
        self.assertEqual({row["predicate"] for row in symbol_impact["direct_callees"]}, {"CALLS"})
        self.assertEqual(result["source_coordinates"][0]["repo"], "payments")
        self.assertIsNone(result["source_coordinates"][0]["commit_sha"])
        self.assertEqual(result["source_coordinates"][0]["provenance"], "row_geometry")
        self.assertEqual(result["source_coordinates"][0]["path"], "payments/checkout.py")
        self.assertEqual(result["source_coordinates"][0]["line_start"], 10)
        self.assertEqual(result["source_coordinates"][0]["line_end"], 20)

    def test_planning_context_symbol_impact_fails_closed_without_resolved_name(self) -> None:
        with _fixture_snapshot() as kg:
            result = _planning_context_symbol_impact(
                kg,
                [{"path": "payments/checkout.py", "line": 10}],
                anchors={"symbol": "handle_checkout"},
                status="found",
            )

        self.assertEqual(result["status"], "not_computed")
        self.assertEqual(result["reason"], "resolved symbol missing qualified name")

    def test_planning_context_source_coordinates_include_bytes_ref_provenance(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"package": "shared-lib", "line": 2})

        self.assertEqual(result["status"], "found")
        coordinates = result["source_coordinates"]
        self.assertTrue(coordinates)
        self.assertEqual(coordinates[0]["repo"], "payments")
        self.assertEqual(coordinates[0]["commit_sha"], "fixture-sha")
        self.assertEqual(coordinates[0]["provenance"], "bytes_ref")
        self.assertEqual(coordinates[0]["path"], "payments/checkout.py")
        self.assertEqual(coordinates[0]["line_start"], 2)
        self.assertEqual(coordinates[0]["line_end"], 2)

    def test_planning_context_answerability_distinguishes_partial_and_not_answerable(self) -> None:
        with _fixture_snapshot() as kg:
            partial = call_tool(kg, "planning_context", {"service": "payments", "package": "missing-package"})
            missing = call_tool(kg, "planning_context", {"service": "missing"})

        self.assertEqual(partial["status"], "found")
        self.assertEqual(partial["answerability"]["status"], "partial")
        self.assertEqual(partial["answerability"]["missing_fact_families"], ["dependency_edges"])
        self.assertTrue(partial["answerability"]["recommended_followups"])
        self.assertEqual(missing["status"], "not_found")
        self.assertEqual(missing["answerability"]["status"], "not_answerable")
        self.assertEqual(missing["answerability"]["missing_fact_families"], ["primary_anchor"])

    def test_planning_context_related_sections_are_capped(self) -> None:
        with _fixture_snapshot(extra_consumers=125) as kg:
            result = call_tool(kg, "planning_context", {"event_channel": "orders-created", "limit": 100})

        self.assertEqual(result["status"], "found")
        self.assertGreater(result["summary"]["event_fact_count"], 5)
        self.assertEqual(len(result["related_facts"]["event_channels"]), 5)
        self.assertEqual(result["summary"]["section_limit"], 5)

    def test_planning_context_structured_endpoint_event_and_domain_anchors(self) -> None:
        with _fixture_snapshot() as kg:
            endpoint = call_tool(kg, "planning_context", {"repo": "payments", "endpoint": "/checkout"})
            event = call_tool(kg, "planning_context", {"repo": "payments", "event_channel": "orders-created"})
            domain = call_tool(kg, "planning_context", {"repo": "payments", "domain": "api.internal.example"})

        self.assertEqual(endpoint["status"], "found")
        self.assertEqual({row["predicate"] for row in endpoint["endpoints"]}, {"EXPOSES_ENDPOINT"})
        self.assertEqual(event["status"], "found")
        self.assertEqual({row["predicate"] for row in event["event_channels"]}, {"CONSUMES_EVENT", "PRODUCES_EVENT"})
        self.assertEqual(domain["status"], "found")
        self.assertEqual({row["predicate"] for row in domain["domains"]}, {"REFERENCES_DOMAIN"})

    def test_planning_context_cross_family_anchors_keep_each_family_context(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "planning_context",
                {"endpoint": "/checkout", "event_channel": "orders-created"},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["answerability"]["status"], "answerable")
        self.assertEqual({row["predicate"] for row in result["endpoints"]}, {"EXPOSES_ENDPOINT"})
        self.assertEqual({row["predicate"] for row in result["event_channels"]}, {"CONSUMES_EVENT", "PRODUCES_EVENT"})

    def test_planning_context_service_enrichment_survives_secondary_anchor(self) -> None:
        with _fixture_snapshot(extra_service_endpoint=True) as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "endpoint": "/checkout", "limit": 10})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["summary"]["endpoint_fact_count"], 2)
        self.assertEqual({row["object"] for row in result["endpoints"]}, {"POST /checkout", "GET /refund"})

    def test_planning_context_missing_identity_followups_are_actionable(self) -> None:
        with _fixture_snapshot() as kg:
            missing_service = call_tool(kg, "planning_context", {"service": "missing", "endpoint": "/checkout"})
            missing_symbol = call_tool(kg, "planning_context", {"symbol": "missing", "endpoint": "/checkout"})

        self.assertEqual(missing_service["answerability"]["missing_fact_families"], ["service_identity"])
        self.assertTrue(any("search_services" in action for action in missing_service["answerability"]["recommended_followups"]))
        self.assertEqual(missing_symbol["answerability"]["missing_fact_families"], ["symbol_identity"])
        self.assertTrue(any("path" in action and "line" in action for action in missing_symbol["answerability"]["recommended_followups"]))

    def test_planning_context_dedupes_same_location_bytes_ref_and_row_geometry(self) -> None:
        with _fixture_snapshot(symbol_entity_evidence_duplicate_coordinates=True) as kg:
            result = call_tool(kg, "planning_context", {"symbol": "handle_checkout"})

        checkout_coordinates = [
            coordinate
            for coordinate in result["source_coordinates"]
            if coordinate["path"] == "payments/checkout.py"
            and coordinate["line_start"] == 10
            and coordinate["line_end"] == 20
        ]
        self.assertEqual(len(checkout_coordinates), 1)
        self.assertEqual(checkout_coordinates[0]["provenance"], "bytes_ref")

    def test_get_service_brief_dedupes_related_rows(self) -> None:
        with _fixture_snapshot(duplicate_endpoint_fact=True) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(len(result["endpoints"]), 1)

    def test_get_service_brief_surfaces_bounded_endpoint_consumers(self) -> None:
        with _fixture_snapshot(endpoint_consumer=True) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["summary"]["endpoint_consumer_fact_count"], 1)
        self.assertEqual(result["summary"]["endpoint_consumer_service_count"], 1)
        packet = result["endpoint_consumers"]
        self.assertEqual(packet["summary"]["consumer_fact_count"], 1)
        self.assertEqual(packet["summary"]["consumer_service_count"], 1)
        self.assertEqual(packet["summary"]["host_resolution_kind_counts"], {"env_backed_unresolved": 1})
        self.assertEqual(packet["consumers"][0]["consumer"]["slug"], "web")
        self.assertEqual(packet["consumers"][0]["matched_provider_endpoint"]["path"], "/checkout")
        self.assertEqual(packet["consumers"][0]["match_basis"], "normalized_endpoint_path_and_compatible_method")
        self.assertTrue(any("endpoint_consumers" in action for action in result["next_actions"]))

    def test_get_service_brief_surfaces_operational_deploy_candidates(self) -> None:
        with _fixture_snapshot(operational_deploy_mapping=True, operational_deploy_same_repo=True) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        self.assertEqual(result["summary"]["deploy_target_candidate_count"], 1)
        self.assertEqual(result["summary"]["domain_route_candidate_count"], 1)
        surfaces = result["operational_surfaces"]
        self.assertEqual(
            surfaces["deploy_target_candidates"][0]["match_basis"],
            "deploy_target_repo_equals_service_repo",
        )
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["status"], "found")
        self.assertEqual(surfaces["evidence_partition"]["unlinked_evidence"]["status"], "empty")
        self.assertTrue(
            any(
                item["contract"] == "canonical_service_deploy_blocker"
                for item in surfaces["evidence_partition"]["missing_contracts"]["items"]
            )
        )
        self.assertEqual(surfaces["domain_route_candidates"][0]["predicate"], "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertIn("exact repo-identity evidence", surfaces["coverage_note"])

    def test_get_service_brief_does_not_infer_deploy_from_target_text(self) -> None:
        with _fixture_snapshot(operational_deploy_mapping=True) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        surfaces = result["operational_surfaces"]
        self.assertEqual(result["summary"]["deploy_target_candidate_count"], 0)
        self.assertEqual(result["summary"]["domain_route_candidate_count"], 0)
        self.assertEqual(surfaces["summary"]["unlinked_domain_route_count"], 1)
        self.assertEqual(surfaces["unlinked_domain_route_samples"][0]["relationship_to_service"], "unlinked_fleet_route")
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["status"], "found")
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["counts"]["domain_route_count"], 0)
        self.assertEqual(surfaces["evidence_partition"]["known_linked"]["counts"]["deploy_target_count"], 0)
        self.assertEqual(surfaces["evidence_partition"]["unlinked_evidence"]["status"], "found")
        self.assertTrue(
            any(
                item["contract"] == "unlinked_route_to_service"
                for item in surfaces["evidence_partition"]["missing_contracts"]["items"]
            )
        )

    def test_get_service_brief_treats_provider_any_method_as_compatible(self) -> None:
        with _fixture_snapshot(
            endpoint_consumer=True,
            provider_endpoint_method="ANY",
            endpoint_consumer_method="GET",
        ) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        self.assertEqual(result["summary"]["endpoint_consumer_fact_count"], 1)
        self.assertEqual(result["endpoint_consumers"]["consumers"][0]["matched_provider_endpoint"]["methods"], ["ANY"])

    def test_get_service_brief_does_not_match_consumers_without_method(self) -> None:
        with _fixture_snapshot(endpoint_consumer=True, endpoint_consumer_method=None) as kg:
            result = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 10})

        self.assertEqual(result["summary"]["endpoint_consumer_fact_count"], 0)
        self.assertEqual(result["endpoint_consumers"]["consumers"], [])

    def test_review_context_aggregates_symbols_and_call_edges(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {"repo": "payments", "changed_files": ["payments/checkout.py"], "limit": 10},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["repo"], "payments")
        self.assertIn("changed_symbols", result)
        self.assertIn("direct_callers", result)
        self.assertIn("direct_callees", result)
        self.assertIn("repo_dependencies", result)
        self.assertTrue(any(row["qualname"] == "handle_checkout" for row in result["changed_symbols"]))
        self.assertEqual({row["predicate"] for row in result["direct_callees"]}, {"CALLS"})
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})
        self.assertEqual(result["answerability"]["status"], "answerable")
        self.assertEqual(result["summary"]["changed_file_count"], 1)
        self.assertEqual(result["summary"]["changed_symbol_count"], 2)
        self.assertEqual(result["changed_surface"]["files"][0]["symbol_count"], 2)
        self.assertEqual(result["changed_surface"]["symbols"][0]["qualname"], "bootstrap_checkout")
        self.assertEqual({row["predicate"] for row in result["impact"]["direct_callees"]}, {"CALLS"})
        self.assertEqual({row["predicate"] for row in result["runtime_surfaces"]["endpoints"]}, {"EXPOSES_ENDPOINT"})
        self.assertEqual(
            {row["predicate"] for row in result["runtime_surfaces"]["event_channels"]},
            {"CONSUMES_EVENT", "PRODUCES_EVENT"},
        )
        self.assertTrue(result["source_coordinates"])
        self.assertEqual(result["source_coordinates"][0]["path"], "payments/checkout.py")
        _assert_additive_fields(self, result)

    def test_review_context_surfaces_path_matched_endpoint_consumers(self) -> None:
        with _fixture_snapshot(endpoint_consumer=True) as kg:
            result = call_tool(
                kg,
                "review_context",
                {"repo": "payments", "changed_files": ["payments/checkout.py"], "limit": 10},
            )

        self.assertEqual(result["summary"]["endpoint_consumer_fact_count"], 1)
        consumer = result["runtime_surfaces"]["endpoint_consumers"][0]
        self.assertEqual(consumer["predicate"], "CALLS_ENDPOINT")
        self.assertEqual(consumer["consumer"]["repo"], "web")
        self.assertEqual(consumer["matched_provider_endpoint"]["methods"], ["POST"])

    def test_review_context_repo_filter_is_case_insensitive(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {"repo": "Payments", "changed_files": ["payments/checkout.py"], "limit": 10},
            )

        self.assertEqual(result["status"], "found")
        self.assertTrue(any(row["qualname"] == "handle_checkout" for row in result["changed_symbols"]))
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_review_context_changed_ranges_filter_symbols(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 10, "end_line": 10}],
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual([row["qualname"] for row in result["changed_symbols"]], ["handle_checkout"])

    def test_review_context_changed_ranges_only_narrow_matching_files(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py", "payments/gateway.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 10, "end_line": 10}],
                    "limit": 10,
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(
            {row["qualname"] for row in result["changed_symbols"]},
            {"handle_checkout", "charge_card"},
        )

    def test_review_context_missing_changed_file_still_returns_repo_dependencies(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/missing.py"]})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["changed_symbols"], [])
        self.assertEqual(result["direct_callers"], [])
        self.assertEqual(result["direct_callees"], [])
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})
        self.assertEqual(result["answerability"]["status"], "partial")
        self.assertEqual(result["answerability"]["missing_fact_families"], ["changed_symbols"])
        self.assertEqual(result["changed_surface"]["files"][0]["symbol_count"], 0)

    def test_review_context_changed_ranges_fail_closed_for_non_overlapping_file(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 30, "end_line": 30}],
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["changed_symbols"], [])
        self.assertEqual(result["direct_callers"], [])
        self.assertEqual(result["direct_callees"], [])
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_review_context_rejects_unknown_arguments(self) -> None:
        with _fixture_snapshot() as kg:
            with self.assertRaisesRegex(ValueError, "does not accept argument\\(s\\): depth"):
                call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/checkout.py"], "depth": 2})
            with self.assertRaisesRegex(ValueError, "changed_ranges"):
                call_tool(
                    kg,
                    "review_context",
                    {
                        "repo": "payments",
                        "changed_files": ["payments/checkout.py"],
                        "changed_ranges": [
                            {"path": "payments/checkout.py", "start_line": 10, "end_line": 10, "extra": "bad"}
                        ],
                    },
                )
            with self.assertRaisesRegex(ValueError, "changed_ranges"):
                call_tool(
                    kg,
                    "review_context",
                    {"repo": "payments", "changed_files": ["payments/checkout.py"], "changed_ranges": None},
                )

    def test_review_context_deploy_blocker_row_is_opt_in(self) -> None:
        with _fixture_snapshot() as kg:
            default = call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/checkout.py"]})
            opted_in = call_tool(
                kg,
                "review_context",
                {"repo": "payments", "changed_files": ["payments/checkout.py"], "include_deploy_blockers": True},
            )

        self.assertEqual(default["unsupported_scopes"], [])
        self.assertEqual(default["unsupported_review_scopes"], [])
        self.assertEqual(
            opted_in["unsupported_scopes"],
            [
                {
                    "kind": "deploy_blockers",
                    "scope": "payments",
                    "reason": "No canonical deploy-blocker relation is implemented yet",
                }
            ],
        )
        self.assertEqual(opted_in["unsupported_review_scopes"], opted_in["unsupported_scopes"])
        self.assertEqual(opted_in["answerability"]["status"], "partial")
        self.assertEqual(opted_in["answerability"]["missing_fact_families"], ["deploy_blockers"])

    def test_search_services_and_service_brief_return_json_shapes(self) -> None:
        with _fixture_snapshot() as kg:
            all_services = call_tool(kg, "search_services", {})
            search = call_tool(kg, "search_services", {"query": "payments"})
            brief = call_tool(kg, "get_service_brief", {"service": "payments"})
            limited_brief = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 1})
            missing = call_tool(kg, "get_service_brief", {"service": "missing"})

        self.assertEqual(all_services["status"], "found")
        self.assertEqual(search["status"], "found")
        self.assertEqual(search["services"][0]["slug"], "payments")
        self.assertEqual(brief["status"], "found")
        self.assertEqual(brief["service"]["slug"], "payments")
        self.assertEqual(brief["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(brief["answerability"]["status"], "partial")
        self.assertEqual(brief["answerability"]["missing_fact_families"], ["deploy_mapping"])
        self.assertTrue(brief["next_actions"])
        self.assertEqual(limited_brief["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(limited_brief["summary"]["event_fact_count"], 1)
        self.assertEqual(brief["summary"]["endpoint_consumer_fact_count"], 0)
        self.assertEqual(len(limited_brief["endpoints"]), 1)
        self.assertEqual(len(limited_brief["event_channels"]), 1)
        self.assertFalse(any(key.startswith("_") for key in brief["endpoints"][0]))
        self.assertEqual(missing["status"], "not_found")
        _assert_additive_fields(self, all_services)
        _assert_additive_fields(self, search)
        _assert_additive_fields(self, brief)
        _assert_additive_fields(self, limited_brief)
        _assert_additive_fields(self, missing)

    def test_symbol_tools_wrap_snapshot_query_methods(self) -> None:
        with _fixture_snapshot() as kg:
            callers = call_tool(kg, "find_callers", {"symbol": "charge_card"})
            callees = call_tool(kg, "find_callees", {"symbol": "handle_checkout"})
            radius = call_tool(kg, "blast_radius", {"symbol": "handle_checkout", "depth": 1})

        self.assertEqual(callers["status"], "found")
        self.assertEqual(callers["caller_count"], 1)
        self.assertEqual(callees["status"], "found")
        self.assertEqual(callees["callee_count"], 1)
        self.assertEqual(radius["status"], "found")
        self.assertEqual(radius["edge_count"], 1)
        _assert_additive_fields(self, callers)
        _assert_additive_fields(self, callees)
        _assert_additive_fields(self, radius)

    def test_discovery_keeps_fuzzy_but_graph_tools_require_exact_symbols(self) -> None:
        with _fixture_snapshot() as kg:
            lookup = kg.lookup_symbol("card")
            planning = call_tool(kg, "planning_context", {"query": "card"})
            callers = call_tool(kg, "find_callers", {"symbol": "card"})
            callees = call_tool(kg, "find_callees", {"symbol": "handle"})
            radius = call_tool(kg, "blast_radius", {"symbol": "handle", "depth": 1})
            dependency = kg.dependency_path("handle", "shared-lib")
            evidence = kg.evidence_for_call("handle_checkout", "card")

        self.assertEqual(lookup["status"], "resolved")
        self.assertEqual(lookup["confidence"], "fuzzy_unique")
        self.assertEqual(lookup["resolved_symbol"]["qualname"], "charge_card")
        self.assertTrue(any(row["qualname"] == "charge_card" for row in planning["symbols"]))
        self.assertEqual(callers["status"], "not_found")
        self.assertEqual(callers["target"]["confidence"], "not_found")
        self.assertTrue(callers["next_actions"])
        self.assertIn("not proof of absence", callers["next_actions"][0])
        self.assertEqual(callees["status"], "not_found")
        self.assertEqual(callees["source"]["confidence"], "not_found")
        self.assertTrue(callees["next_actions"])
        self.assertEqual(radius["status"], "not_found")
        self.assertEqual(radius["source"]["confidence"], "not_found")
        self.assertTrue(radius["next_actions"])
        self.assertEqual(dependency["status"], "not_found")
        self.assertEqual(dependency["source"]["confidence"], "not_found")
        self.assertEqual(evidence["status"], "not_found")
        self.assertEqual(evidence["callee"]["confidence"], "not_found")

    def test_event_tools_filter_consumers_and_producers(self) -> None:
        with _fixture_snapshot() as kg:
            consumers = call_tool(kg, "get_event_consumers", {"channel": "orders"})
            producers = call_tool(kg, "get_event_producers", {"channel": "orders"})
            limited_producers = call_tool(kg, "get_event_producers", {"channel": "orders", "limit": 1})

        self.assertEqual(consumers["status"], "found")
        self.assertEqual(consumers["returned_count"], 1)
        self.assertEqual(consumers["consumers"][0]["predicate"], "CONSUMES_EVENT")
        self.assertEqual(producers["status"], "found")
        self.assertEqual(producers["returned_count"], 1)
        self.assertEqual(producers["producers"][0]["predicate"], "PRODUCES_EVENT")
        self.assertEqual(limited_producers["status"], "found")
        self.assertEqual(consumers["answerability"]["status"], "answerable")
        self.assertEqual(consumers["answerability"]["missing_fact_families"], [])
        self.assertTrue(any("time-window usage" in action for action in consumers["next_actions"]))
        _assert_additive_fields(self, consumers)
        _assert_additive_fields(self, producers)
        _assert_additive_fields(self, limited_producers)

    def test_event_tools_not_found_distinguish_static_miss_from_runtime_proof(self) -> None:
        with _fixture_snapshot() as kg:
            consumers = call_tool(kg, "get_event_consumers", {"channel": "missing-channel"})

        self.assertEqual(consumers["status"], "not_found")
        self.assertEqual(consumers["answerability"]["status"], "partial")
        self.assertEqual(consumers["answerability"]["missing_fact_families"], ["static_event_facts"])
        self.assertTrue(any("no indexed static event facts" in action for action in consumers["next_actions"]))

    def test_event_tools_scan_all_matching_facts_before_limiting(self) -> None:
        with _fixture_snapshot(extra_consumers=125) as kg:
            consumers = call_tool(kg, "get_event_consumers", {"channel": "orders", "limit": 1})
            producers = call_tool(kg, "get_event_producers", {"channel": "orders", "limit": 1})

        self.assertEqual(consumers["event_fact_count"], 126)
        self.assertEqual(consumers["returned_count"], 1)
        self.assertEqual(producers["event_fact_count"], 1)
        self.assertEqual(producers["returned_count"], 1)

    def test_deploy_blockers_refuses_when_current_kg_has_no_contract(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "deploy_blockers_for", {"service": "payments"})

        self.assertEqual(result["status"], "unsupported_by_current_kg")
        self.assertEqual(result["missing_contract"], "deploy_blockers_for")
        self.assertTrue(result["unsupported_scopes"])
        self.assertTrue(any("deployment manifests" in action for action in result["next_actions"]))
        _assert_additive_fields(self, result)

    def test_tool_arguments_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            with self.assertRaisesRegex(ValueError, "symbol"):
                call_tool(kg, "find_callers", {"limit": 10})
            with self.assertRaisesRegex(ValueError, "limit"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": True})
            with self.assertRaisesRegex(ValueError, "limit"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": "10"})
            with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": 0})
            with self.assertRaisesRegex(ValueError, "between 1 and 6"):
                call_tool(kg, "blast_radius", {"symbol": "x", "depth": 999})
            with self.assertRaisesRegex(ValueError, "does not accept"):
                call_tool(kg, "find_callers", {"symbol": "x", "extra": "ignored"})
            with self.assertRaisesRegex(ValueError, "Unsupported MCP tool"):
                call_tool(kg, "unknown_tool", {})

    def test_json_rpc_lists_and_calls_tools(self) -> None:
        with _fixture_snapshot() as kg:
            initialized = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
            initialized_with_client_version = _handle_json_rpc(
                kg,
                {"jsonrpc": "2.0", "id": 8, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}},
            )
            ping = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
            listed = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            batch = _handle_json_rpc_payload(
                kg,
                [
                    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                    {"jsonrpc": "2.0", "method": "ping"},
                ],
            )
            called = _handle_json_rpc(
                kg,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "search_services", "arguments": {"query": "payments"}},
                },
            )
            unsupported = _handle_json_rpc(
                kg,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "deploy_blockers_for", "arguments": {"service": "payments"}},
                },
            )

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "supercontext-local")
        self.assertEqual(initialized["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertIn("instructions", initialized["result"])
        instructions = initialized["result"]["instructions"]
        self.assertIn("planning_context first", instructions)
        self.assertIn("review_context first", instructions)
        self.assertIn("inspect the relevant workspace source files", instructions)
        self.assertIn("service_operational_surfaces.evidence_partition", instructions)
        self.assertIn("known_linked", instructions)
        self.assertIn("unlinked_evidence", instructions)
        self.assertIn("missing_contracts", instructions)
        self.assertEqual(initialized_with_client_version["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(initialized_with_client_version["result"]["instructions"], instructions)
        self.assertEqual(ping["result"], {})
        self.assertEqual(batch[0]["id"], 3)
        self.assertEqual(listed["result"]["tools"][0]["name"], "search_services")
        listed_tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
        self.assertIn("downstream static CALLS closure", listed_tools["blast_radius"]["description"])
        self.assertEqual(called["result"]["structuredContent"]["status"], "found")
        _assert_additive_fields(self, called["result"]["structuredContent"])
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(unsupported["result"]["structuredContent"]["status"], "unsupported_by_current_kg")
        self.assertFalse(unsupported["result"]["isError"])

    def test_json_rpc_reports_protocol_errors(self) -> None:
        with _fixture_snapshot() as kg:
            result = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}})
            wrong_version = _handle_json_rpc(kg, {"jsonrpc": "1.0", "id": 2, "method": "ping"})
            notification = _handle_json_rpc(kg, {"jsonrpc": "2.0", "method": "ping"})
            invalid_notification_version = _handle_json_rpc(kg, {"jsonrpc": "1.0", "method": "ping"})
            invalid_notification_method = _handle_json_rpc(kg, {"jsonrpc": "2.0"})
            invalid_notification_params = _handle_json_rpc(kg, {"jsonrpc": "2.0", "method": "ping", "params": []})
            empty_batch = _handle_json_rpc_payload(kg, [])
            notification_batch = _handle_json_rpc_payload(kg, [{"jsonrpc": "2.0", "method": "ping"}])
            invalid_id = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "ping"})

        self.assertEqual(result["error"]["code"], -32602)
        self.assertIn("name", result["error"]["message"])
        self.assertEqual(wrong_version["error"]["code"], -32600)
        self.assertIsNone(notification)
        self.assertEqual(invalid_notification_version["error"]["code"], -32600)
        self.assertEqual(invalid_notification_method["error"]["code"], -32600)
        self.assertEqual(invalid_notification_params["error"]["code"], -32602)
        self.assertEqual(empty_batch["error"]["code"], -32600)
        self.assertIsNone(notification_batch)
        self.assertEqual(invalid_id["error"]["code"], -32600)

    def test_json_rpc_internal_errors_do_not_leak_exception_details(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = _handle_json_rpc(
                object(),
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "search_services", "arguments": {}},
                },
            )

        self.assertEqual(result["error"]["code"], -32000)
        self.assertEqual(result["error"]["message"], "Internal MCP server error")
        self.assertIn("Unhandled MCP JSON-RPC error", stderr.getvalue())
        self.assertIn("AttributeError", stderr.getvalue())

    def test_content_length_validation_rejects_transport_level_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing Content-Length"):
            _content_length(_FakeHttpHandler({}))
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            _content_length(_FakeHttpHandler({"Content-Length": "abc"}))
        with self.assertRaisesRegex(ValueError, "outside the accepted range"):
            _content_length(_FakeHttpHandler({"Content-Length": "1000001"}))

        self.assertEqual(_content_length(_FakeHttpHandler({"Content-Length": "2"})), 2)

    def test_request_body_read_sets_timeout_and_rejects_incomplete_body(self) -> None:
        complete = _FakeHttpHandler({"Content-Length": "2"}, body=b"{}")
        short = _FakeHttpHandler({"Content-Length": "4"}, body=b"{}")
        stalled = _FakeHttpHandler({"Content-Length": "2"}, rfile=_TimeoutReader())

        self.assertEqual(_read_request_body(complete, 2), b"{}")
        self.assertEqual(complete.connection.timeout, REQUEST_READ_TIMEOUT_SECONDS)
        with self.assertRaisesRegex(ValueError, "before Content-Length"):
            _read_request_body(short, 4)
        with self.assertRaisesRegex(_RequestBodyTimeout, "Timed out"):
            _read_request_body(stalled, 2)

    def test_json_body_decoding_reports_invalid_utf8_as_parse_error(self) -> None:
        with self.assertRaisesRegex(_JsonPayloadError, "invalid UTF-8"):
            _decode_json_payload(b"\xff")
        with self.assertRaisesRegex(_JsonPayloadError, "Expecting value"):
            _decode_json_payload(b"not-json")

        self.assertEqual(_decode_json_payload(b'{"ok": true}'), {"ok": True})

    def test_loopback_host_detection_accepts_loopback_network(self) -> None:
        self.assertTrue(_is_loopback_host("localhost"))
        self.assertTrue(_is_loopback_host("127.0.0.1"))
        self.assertTrue(_is_loopback_host("127.0.1.1"))
        self.assertTrue(_is_loopback_host("::1"))
        self.assertFalse(_is_loopback_host("0.0.0.0"))
        self.assertFalse(_is_loopback_host("example.com"))
        self.assertEqual(_format_host_for_url("127.0.0.1"), "127.0.0.1")
        self.assertEqual(_format_host_for_url("::1"), "[::1]")
        self.assertEqual(_format_host_for_url("localhost"), "localhost")
        self.assertEqual(_server_address_for_host("127.0.0.1", 3845), ("127.0.0.1", 3845))
        self.assertEqual(_server_address_for_host("::1", 3845), ("::1", 3845, 0, 0))
        self.assertNotEqual(_server_class_for_host("::1").address_family, _server_class_for_host("127.0.0.1").address_family)

    def test_http_server_header_does_not_expose_python_version(self) -> None:
        handler = _handler_class(object())
        fake_handler = type("FakeHandler", (), {"server_version": handler.server_version})()

        self.assertEqual(handler.sys_version, "")
        self.assertEqual(handler.version_string(fake_handler), "supercontext-local/0.1.0")


class _fixture_snapshot:
    def __init__(
        self,
        extra_consumers: int = 0,
        extra_package_importers: int = 0,
        extra_charge_card_symbol: bool = False,
        duplicate_endpoint_fact: bool = False,
        extra_service_endpoint: bool = False,
        endpoint_consumer: bool = False,
        provider_endpoint_method: str = "POST",
        endpoint_consumer_method: str | None = "POST",
        operational_deploy_mapping: bool = False,
        operational_deploy_same_repo: bool = False,
        symbol_entity_evidence_duplicate_coordinates: bool = False,
    ) -> None:
        self.extra_consumers = extra_consumers
        self.extra_package_importers = extra_package_importers
        self.extra_charge_card_symbol = extra_charge_card_symbol
        self.duplicate_endpoint_fact = duplicate_endpoint_fact
        self.extra_service_endpoint = extra_service_endpoint
        self.endpoint_consumer = endpoint_consumer
        self.provider_endpoint_method = provider_endpoint_method
        self.endpoint_consumer_method = endpoint_consumer_method
        self.operational_deploy_mapping = operational_deploy_mapping
        self.operational_deploy_same_repo = operational_deploy_same_repo
        self.symbol_entity_evidence_duplicate_coordinates = symbol_entity_evidence_duplicate_coordinates

    def __enter__(self) -> KgSnapshot:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        service = Entity(
            kind="Service",
            identity={"tenant_id": "default", "namespace": "default", "slug": "payments", "repo": "payments"},
        )
        caller = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.checkout",
                "qualname": "handle_checkout",
                "symbol_kind": "function",
            },
            properties={"path": "payments/checkout.py", "line": 10, "end_line": 20},
        )
        earlier_symbol = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.checkout",
                "qualname": "bootstrap_checkout",
                "symbol_kind": "function",
            },
            properties={"path": "payments/checkout.py", "line": 1, "end_line": 3},
        )
        module = Entity(
            kind="CodeModule",
            identity={"tenant_id": "default", "repo": "payments", "module": "payments.checkout"},
            properties={"path": "payments/checkout.py"},
        )
        callee = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.gateway",
                "qualname": "charge_card",
                "symbol_kind": "function",
            },
            properties={"path": "payments/gateway.py", "line": 5, "end_line": 12},
        )
        endpoint = Entity(
            kind="Endpoint",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "protocol": "http",
                "method": self.provider_endpoint_method,
                "path": "/checkout",
                "host": None,
            },
        )
        extra_endpoint = Entity(
            kind="Endpoint",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "protocol": "http",
                "method": "GET",
                "path": "/refund",
                "host": None,
            },
        )
        consumer_service = Entity(
            kind="Service",
            identity={"tenant_id": "default", "namespace": "default", "slug": "web", "repo": "web"},
        )
        consumer_endpoint = Entity(
            kind="Endpoint",
            identity={
                "tenant_id": "default",
                "repo": "web",
                "protocol": "http",
                "method": self.endpoint_consumer_method,
                "path": "/checkout",
                "host": "${env:PAYMENTS_API_BASE_URL}",
            },
        )
        channel = Entity(
            kind="EventChannel",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "broker_kind": "sqs",
                "channel_address": "orders-created",
                "name": "orders-created",
            },
        )
        domain = Entity(
            kind="Domain",
            identity={"tenant_id": "default", "repo": "payments", "name": "api.internal.example"},
        )
        operational_deploy_repo = "payments" if self.operational_deploy_same_repo else "ops"
        route_domain = Entity(
            kind="Domain",
            identity={"tenant_id": "default", "repo": operational_deploy_repo, "name": "payments.example.com"},
        )
        deploy_target = Entity(
            kind="DeployTarget",
            identity={"tenant_id": "default", "repo": operational_deploy_repo, "type": "wsgi", "target": "/srv/payments/app.wsgi"},
        )
        env_var = Entity(
            kind="EnvVar",
            identity={"tenant_id": "default", "repo": "payments", "name": "PAYMENTS_API_BASE_URL"},
        )
        package = Entity(
            kind="ExternalPackage",
            identity={"tenant_id": "default", "repo": "payments", "name": "shared-lib"},
            properties={"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
        )
        provider_repo = Entity(
            kind="Repo",
            identity={"tenant_id": "default", "host": "local", "owner": "default", "name": "shared-platform"},
        )
        duplicate_callee = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.alt_gateway",
                "qualname": "charge_card",
                "symbol_kind": "function",
            },
            properties={"path": "payments/alt_gateway.py", "line": 7, "end_line": 9},
        )
        call_fact = Fact("CALLS", caller.entity_id, callee.entity_id)
        import_fact = Fact(
            "IMPORTS",
            module.entity_id,
            package.entity_id,
            {"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
        )
        repo_link_fact = Fact(
            "RESOLVES_TO_REPO",
            package.entity_id,
            provider_repo.entity_id,
            {"consumer_repo": "payments", "package_name": "shared-lib"},
        )
        endpoint_fact = Fact(
            "EXPOSES_ENDPOINT",
            service.entity_id,
            endpoint.entity_id,
            {"method": self.provider_endpoint_method, "path": "/checkout"},
        )
        extra_endpoint_fact = Fact(
            "EXPOSES_ENDPOINT",
            service.entity_id,
            extra_endpoint.entity_id,
            {"method": "GET", "path": "/refund"},
        )
        endpoint_consumer_fact = Fact(
            "CALLS_ENDPOINT",
            consumer_service.entity_id,
            consumer_endpoint.entity_id,
            {
                "confidence": "host_unresolved_path_resolved",
                "host_resolution_kind": "env_backed_unresolved",
                "method": self.endpoint_consumer_method,
                "path": "/checkout",
                "raw_target": "${env:PAYMENTS_API_BASE_URL}/checkout",
                "resolution_kind": "path_resolved",
                "source_kind": "http_client",
            },
        )
        consume_fact = Fact("CONSUMES_EVENT", service.entity_id, channel.entity_id)
        produce_fact = Fact("PRODUCES_EVENT", caller.entity_id, channel.entity_id)
        domain_fact = Fact("REFERENCES_DOMAIN", env_var.entity_id, domain.entity_id)
        route_fact = Fact("ROUTES_DOMAIN_TO_DEPLOY", route_domain.entity_id, deploy_target.entity_id, {"source_kind": "fixture_vhost"})
        extra_services = [
            Entity(
                kind="Service",
                identity={
                    "tenant_id": "default",
                    "namespace": "default",
                    "slug": f"consumer-{index}",
                    "repo": f"consumer-{index}",
                },
            )
            for index in range(self.extra_consumers)
        ]
        extra_modules = [
            Entity(
                kind="CodeModule",
                identity={"tenant_id": "default", "repo": "payments", "module": f"payments.importer_{index}"},
                properties={"path": f"payments/importer_{index}.py"},
            )
            for index in range(self.extra_package_importers)
        ]
        extra_consume_facts = [Fact("CONSUMES_EVENT", extra_service.entity_id, channel.entity_id) for extra_service in extra_services]
        extra_import_facts = [
            Fact(
                "IMPORTS",
                extra_module.entity_id,
                package.entity_id,
                {"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
            )
            for extra_module in extra_modules
        ]
        evidence = [
            Evidence(
                target_type="entity",
                target_id=service.entity_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                confidence=1.0,
            ),
            Evidence(
                target_type="fact",
                target_id=call_fact.fact_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                bytes_ref={"repo": "payments", "path": "payments/checkout.py", "line_start": 14, "line_end": 14},
                confidence=1.0,
            ),
            Evidence(
                target_type="fact",
                target_id=import_fact.fact_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                bytes_ref={
                    "repo": "payments",
                    "commit_sha": "fixture-sha",
                    "path": "payments/checkout.py",
                    "line_start": 2,
                    "line_end": 2,
                },
                confidence=1.0,
            ),
        ]
        if self.symbol_entity_evidence_duplicate_coordinates:
            evidence.append(
                Evidence(
                    target_type="entity",
                    target_id=caller.entity_id,
                    derivation_class="deterministic_static",
                    source_system="test",
                    source_ref={"repo": "payments"},
                    bytes_ref={
                        "repo": "payments",
                        "commit_sha": "fixture-sha",
                        "path": "payments/checkout.py",
                        "line_start": 10,
                        "line_end": 20,
                    },
                    confidence=1.0,
                )
            )
        if self.endpoint_consumer:
            evidence.append(
                Evidence(
                    target_type="fact",
                    target_id=endpoint_consumer_fact.fact_id,
                    derivation_class="deterministic_static",
                    source_system="test",
                    source_ref={"repo": "web"},
                    bytes_ref={"repo": "web", "path": "web/src/api.ts", "line_start": 42, "line_end": 42},
                    confidence=0.8,
                )
            )
        if self.operational_deploy_mapping:
            evidence.append(
                Evidence(
                    target_type="fact",
                    target_id=route_fact.fact_id,
                    derivation_class="deterministic_static",
                    source_system="test",
                    source_ref={"repo": "ops"},
                    bytes_ref={"repo": "ops", "path": "ops/payments.conf", "line_start": 3, "line_end": 8},
                    confidence=1.0,
                )
            )
        entities = [
            service,
            caller,
            earlier_symbol,
            module,
            callee,
            endpoint,
            *([extra_endpoint] if self.extra_service_endpoint else []),
            *([consumer_service, consumer_endpoint] if self.endpoint_consumer else []),
            channel,
            domain,
            *([route_domain, deploy_target] if self.operational_deploy_mapping else []),
            env_var,
            package,
            provider_repo,
            *([duplicate_callee] if self.extra_charge_card_symbol else []),
            *extra_services,
            *extra_modules,
        ]
        facts = [
            call_fact,
            import_fact,
            repo_link_fact,
            endpoint_fact,
            *([extra_endpoint_fact] if self.extra_service_endpoint else []),
            *([endpoint_consumer_fact] if self.endpoint_consumer else []),
            consume_fact,
            produce_fact,
            domain_fact,
            *([route_fact] if self.operational_deploy_mapping else []),
            *([endpoint_fact] if self.duplicate_endpoint_fact else []),
            *extra_consume_facts,
            *extra_import_facts,
        ]
        JsonlKgStore(root).write(
            entities=entities,
            facts=facts,
            evidence=evidence,
            coverage=[],
            manifest={"counts": {"entities": len(entities), "facts": len(facts)}},
        )
        self._kg = KgSnapshot(root)
        return self._kg

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._tmpdir.cleanup()


class _FakeHttpHandler:
    def __init__(self, headers: dict[str, str], *, body: bytes = b"", rfile: object | None = None) -> None:
        self.headers = headers
        self.connection = _FakeConnection()
        self.rfile = rfile or io.BytesIO(body)


class _FakeConnection:
    def __init__(self) -> None:
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class _TimeoutReader:
    def read(self, size: int) -> bytes:
        raise TimeoutError("stalled")


if __name__ == "__main__":
    unittest.main()
