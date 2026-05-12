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
        return {"status": "found", "query": path_query, "endpoints": []}

    def repo_dependencies(self, repo: str, limit: int) -> dict:
        return {"status": "found", "repo": repo, "dependencies": []}


if __name__ == "__main__":
    unittest.main()
