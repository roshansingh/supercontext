from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from source.kg.product import EvidencePacketBuilder


def _load_scenario_plans_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "private-goldset" / "scenario_plans.py"
    spec = importlib.util.spec_from_file_location("private_goldset_scenario_plans", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrivateGoldsetScenarioPlansTest(unittest.TestCase):
    def test_symbol_lookup_rows_become_evidence_items(self) -> None:
        packet = EvidencePacketBuilder("Q999", "query", "shape").build(
            [
                {
                    "step": "symbol_step",
                    "command": "symbols",
                    "args": {"query": "Billing"},
                    "purpose": "Find symbols.",
                    "result": _FakeKg().lookup_symbol("Billing", limit=25),
                }
            ]
        )

        self.assertEqual(len(packet["evidence_items"]), 1)
        item = packet["evidence_items"][0]
        self.assertEqual(item["fact_type"], "SYMBOL")
        self.assertEqual(item["subject"], "billing.views.stripe.StripeView")
        self.assertEqual(item["repo"], "mercury_api")
        self.assertEqual(item["path"], "billing/views/stripe.py")

    def test_symbol_lookup_candidate_without_evidence_is_preserved(self) -> None:
        packet = EvidencePacketBuilder("Q999", "query", "shape").build(
            [
                {
                    "step": "symbol_step",
                    "command": "symbols",
                    "args": {"query": "Billing"},
                    "purpose": "Find symbols.",
                    "result": {
                        "status": "resolved",
                        "candidates": [
                            {
                                "symbol_id": "ent_symbol",
                                "display_name": "billing.views.stripe.StripeView",
                                "qualified_name": "billing.views.stripe.StripeView",
                                "repo": "mercury_api",
                                "module": "billing.views.stripe",
                                "symbol_kind": "class",
                                "evidence": [],
                            }
                        ],
                    },
                }
            ]
        )

        self.assertEqual(len(packet["evidence_items"]), 1)
        item = packet["evidence_items"][0]
        self.assertEqual(item["fact_type"], "SYMBOL")
        self.assertEqual(item["subject"], "billing.views.stripe.StripeView")
        self.assertIsNone(item["path"])

    def test_q081_runtime_topology_plan_records_missing_ml_api_deploy_mapping(self) -> None:
        module = _load_scenario_plans_module()
        plan = module.SCENARIO_PLANS["Q081"]

        packet = EvidencePacketBuilder(
            scenario_id=plan.scenario_id,
            user_query=plan.user_query,
            expected_answer_shape=plan.expected_answer_shape,
        ).build(plan.run(_FakeKg()))

        self.assertEqual(packet["scenario_id"], "Q081")
        self.assertEqual(packet["user_query"], plan.user_query)
        self.assertIn("Runtime topology map", packet["expected_answer_shape"])
        self.assertEqual(len(packet["retrieval_steps"]), 9)
        self.assertEqual(
            [step["step"] for step in packet["retrieval_steps"]],
            [
                "domain_api_shopagain",
                "deploy_prod_shopagain_wsgi",
                "domain_app_shopagain",
                "domain_webhooks_shopagain",
                "domain_tracking_shopagainmail",
                "campaign_messages_queue",
                "websocket_post_chat_message",
                "ml_api_depends_on_ml_library",
                "deploy_prod_ml_api",
            ],
        )
        self.assertEqual(
            packet["unknowns"],
            [
                {
                    "step": "deploy_prod_ml_api",
                    "command": "deploy_mappings",
                    "reason": "No facts returned for Check whether the KG can prove the ML API deploy target from Apache/WSGI config.",
                }
            ],
        )

    def test_q084_stripe_billing_plan_contract(self) -> None:
        module = _load_scenario_plans_module()
        plan = module.SCENARIO_PLANS["Q084"]

        packet = EvidencePacketBuilder(
            scenario_id=plan.scenario_id,
            user_query=plan.user_query,
            expected_answer_shape=plan.expected_answer_shape,
        ).build(plan.run(_FakeKg()))

        self.assertEqual(packet["scenario_id"], "Q084")
        self.assertIn("Feature-slice impact map", packet["expected_answer_shape"])
        self.assertEqual(
            [step["step"] for step in packet["retrieval_steps"]],
            [
                "ui_billing_screen_symbols",
                "ui_billing_route_symbols",
                "backend_stripe_endpoints",
                "backend_create_charge_endpoint",
                "backend_stripe_symbols",
                "stripe_event_channel",
                "stripe_queue_consumer_symbols",
                "stripe_queue_command_symbols",
            ],
        )
        self.assertEqual(packet["unknowns"], [])
        self.assertTrue([item for item in packet["evidence_items"] if item["fact_type"] == "SYMBOL"])

    def test_q092_live_chat_plan_records_missing_exact_backend_callback(self) -> None:
        module = _load_scenario_plans_module()
        plan = module.SCENARIO_PLANS["Q092"]

        packet = EvidencePacketBuilder(
            scenario_id=plan.scenario_id,
            user_query=plan.user_query,
            expected_answer_shape=plan.expected_answer_shape,
        ).build(plan.run(_FakeKg()))

        self.assertEqual(packet["scenario_id"], "Q092")
        self.assertIn("End-to-end live-chat topology", packet["expected_answer_shape"])
        self.assertEqual(
            [step["step"] for step in packet["retrieval_steps"]],
            [
                "storefront_script_symbols",
                "widget_model_symbols",
                "websocket_post_chat_route",
                "websocket_get_history_route",
                "websocket_handler_symbols",
                "backend_live_chat_symbols",
                "chat_endpoint_inventory",
                "operator_conversation_symbols",
                "backend_live_chat_endpoint",
            ],
        )
        self.assertEqual(
            packet["unknowns"],
            [
                {
                    "step": "backend_live_chat_endpoint",
                    "command": "endpoints",
                    "reason": "No facts returned for Check whether the KG can prove the exact backend live-chat callback endpoint.",
                }
            ],
        )


class _FakeKg:
    # Simulates the current production gap: prod_ml_api.conf lacks ServerName,
    # so deploy_mappings cannot prove a domain-to-deploy fact yet.
    def domain_references(self, domain: str, limit: int) -> dict:
        return {"status": "found", "query": domain, "references": []}

    def deploy_mappings(self, target_query: str | None, limit: int) -> dict:
        if target_query == "prod_ml_api":
            return {"status": "not_found", "query": target_query, "mappings": []}
        return {"status": "found", "query": target_query, "mappings": []}

    def event_channels(self, channel_query: str | None, limit: int) -> dict:
        return {"status": "found", "query": channel_query, "event_channels": []}

    def endpoints(self, path_query: str | None, limit: int) -> dict:
        if path_query == "campaigns/live_chat":
            return {"status": "not_found", "query": path_query, "endpoints": []}
        return {"status": "found", "query": path_query, "endpoints": []}

    def repo_dependencies(self, repo: str, limit: int) -> dict:
        return {"status": "found", "repo": repo, "dependencies": []}

    def lookup_symbol(self, query: str, limit: int) -> dict:
        return {
            "status": "resolved",
            "query": query,
            "candidate_count": 1,
            "candidates": [
                {
                    "symbol_id": "ent_symbol",
                    "display_name": "billing.views.stripe.StripeView",
                    "qualified_name": "billing.views.stripe.StripeView",
                    "repo": "mercury_api",
                    "module": "billing.views.stripe",
                    "symbol_kind": "class",
                    "evidence": [
                        {
                            "bytes_ref": {
                                "repo": "mercury_api",
                                "commit_sha": "sha",
                                "path": "billing/views/stripe.py",
                                "line_start": 1,
                                "line_end": 20,
                            },
                            "confidence": 1.0,
                            "derivation_class": "deterministic_static",
                            "source_system": "python_ast_v0",
                        }
                    ],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
