from __future__ import annotations

import unittest

from source.kg.core.models import JsonObject
from source.kg.product.retrieval_planner import (
    RetrievalAnchor,
    RetrievalStep,
    plan_retrieval_steps,
    plan_retrieval_steps_from_mappings,
)


class RetrievalPlannerTest(unittest.TestCase):
    def test_maps_explicit_anchors_to_existing_query_commands(self) -> None:
        steps = plan_retrieval_steps(
            (
                RetrievalAnchor("Domain", "api.example.com"),
                RetrievalAnchor("DeployTarget", "prod_wsgi.py"),
                RetrievalAnchor("Endpoint", "/api/token"),
                RetrievalAnchor("EventChannel", "orders"),
                RetrievalAnchor("Package", "shared_client"),
                RetrievalAnchor("Repo", "web"),
                RetrievalAnchor("Symbol", "BillingView"),
            ),
            limit=200,
        )

        self.assertEqual(
            [(step.name, step.command, step.args) for step in steps],
            [
                ("domain_api_example_com", "domain_references", {"domain": "api.example.com", "limit": 100}),
                ("deploytarget_prod_wsgi_py", "deploy_mappings", {"target": "prod_wsgi.py", "limit": 100}),
                ("endpoint_api_token", "endpoints", {"path": "/api/token", "limit": 100}),
                ("eventchannel_orders", "event_channels", {"channel": "orders", "limit": 100}),
                ("package_shared_client", "modules_importing", {"package": "shared_client", "limit": 100}),
                ("repo_web", "repo_dependencies", {"repo": "web", "limit": 100}),
                ("symbol_billingview", "symbols", {"query": "BillingView", "limit": 100}),
            ],
        )

    def test_dedupes_duplicate_anchors_without_reordering(self) -> None:
        steps = plan_retrieval_steps(
            (
                RetrievalAnchor("Domain", " api.example.com "),
                RetrievalAnchor("Domain", "api.example.com"),
                RetrievalAnchor("Domain", "cdn.example.com"),
            )
        )

        self.assertEqual([step.args["domain"] for step in steps], ["api.example.com", "cdn.example.com"])

    def test_mapping_input_validates_shape(self) -> None:
        steps = plan_retrieval_steps_from_mappings(({"kind": " Domain ", "value": " api.example.com "},))

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].args["domain"], "api.example.com")

    def test_unsupported_anchor_kind_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported retrieval anchor kind"):
            plan_retrieval_steps_from_mappings(({"kind": "Service", "value": "payments"},))

    def test_blank_anchor_value_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty string value"):
            plan_retrieval_steps_from_mappings(({"kind": "Domain", "value": "  "},))

    def test_non_mapping_anchor_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            plan_retrieval_steps_from_mappings((["Domain", "api.example.com"],))  # type: ignore[list-item]

    def test_retrieval_step_runs_mapped_snapshot_method(self) -> None:
        cases = (
            (
                RetrievalStep("deploytarget_prod_wsgi_py", "deploy_mappings", {"target": "prod_wsgi.py", "limit": 5}, "Find deploy."),
                {"method": "deploy_mappings", "target": "prod_wsgi.py", "limit": 5},
                ("deploy_mappings", "prod_wsgi.py", 5),
            ),
            (
                RetrievalStep("domain_api_example_com", "domain_references", {"domain": "api.example.com", "limit": 5}, "Find domain."),
                {"method": "domain_references", "domain": "api.example.com", "limit": 5},
                ("domain_references", "api.example.com", 5),
            ),
            (
                RetrievalStep("endpoint_api_token", "endpoints", {"path": "/api/token", "limit": 5}, "Find endpoint."),
                {"method": "endpoints", "path": "/api/token", "limit": 5},
                ("endpoints", "/api/token", 5),
            ),
            (
                RetrievalStep("eventchannel_orders", "event_channels", {"channel": "orders", "limit": 5}, "Find event."),
                {"method": "event_channels", "channel": "orders", "limit": 5},
                ("event_channels", "orders", 5),
            ),
            (
                RetrievalStep("package_shared_client", "modules_importing", {"package": "shared_client", "limit": 5}, "Find imports."),
                [{"method": "modules_importing", "package": "shared_client", "limit": 5}],
                ("modules_importing", "shared_client", 5),
            ),
            (
                RetrievalStep("repo_web", "repo_dependencies", {"repo": "web", "limit": 5}, "Find repo dependencies."),
                {"method": "repo_dependencies", "repo": "web", "limit": 5},
                ("repo_dependencies", "web", 5),
            ),
            (
                RetrievalStep("symbol_billingview", "symbols", {"query": "BillingView", "limit": 5}, "Find symbol."),
                {"method": "lookup_symbol", "query": "BillingView", "limit": 5},
                ("lookup_symbol", "BillingView", 5),
            ),
        )

        for step, expected_result, expected_call in cases:
            with self.subTest(command=step.command):
                kg = _FakeSnapshot()
                self.assertEqual(step.run(kg), expected_result)
                self.assertEqual(kg.calls, [expected_call])

    def test_invalid_step_command_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported retrieval command"):
            RetrievalStep(
                name="bad",
                command="not_a_command",  # type: ignore[arg-type]
                args={},
                purpose="Invalid command.",
            )

    def test_step_shape_validation_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty string name"):
            RetrievalStep("", "domain_references", {"domain": "api.example.com"}, "Find domain.")
        with self.assertRaisesRegex(ValueError, "args to be a mapping"):
            RetrievalStep("domain", "domain_references", [], "Find domain.")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "requires a non-empty string domain arg"):
            RetrievalStep("domain", "domain_references", {}, "Find domain.")
        with self.assertRaisesRegex(ValueError, "requires a non-empty string domain arg"):
            RetrievalStep("domain", "domain_references", {"domain": "  "}, "Find domain.")
        with self.assertRaises(ValueError):
            RetrievalStep("domain", "domain_references", {"domain": "api.example.com", "limit": "many"}, "Find domain.")
        with self.assertRaises(ValueError):
            RetrievalStep("domain", "domain_references", {"domain": "api.example.com", "limit": None}, "Find domain.")
        with self.assertRaises(ValueError):
            RetrievalStep("domain", "domain_references", {"domain": "api.example.com", "limit": True}, "Find domain.")
        with self.assertRaisesRegex(ValueError, "non-empty string purpose"):
            RetrievalStep("domain", "domain_references", {"domain": "api.example.com"}, "")

    def test_step_args_are_normalized_at_construction(self) -> None:
        step = RetrievalStep(
            "domain",
            "domain_references",
            {"domain": " api.example.com ", "limit": 200},
            "Find domain.",
        )

        self.assertEqual(step.args, {"domain": "api.example.com", "limit": 100})

    def test_limit_boundaries_are_clamped(self) -> None:
        cases = ((-5, 1), (0, 1), (1, 1), (100, 100), (101, 100))
        for requested, expected in cases:
            with self.subTest(requested=requested):
                steps = plan_retrieval_steps((RetrievalAnchor("Domain", "api.example.com"),), limit=requested)
                self.assertEqual(steps[0].args["limit"], expected)

    def test_empty_anchor_list_returns_empty_plan(self) -> None:
        self.assertEqual(plan_retrieval_steps([]), ())


class _FakeSnapshot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def deploy_mappings(self, target_query: str | None = None, limit: int = 25) -> JsonObject:
        self.calls.append(("deploy_mappings", target_query, limit))
        return {"method": "deploy_mappings", "target": target_query, "limit": limit}

    def domain_references(self, domain_query: str, limit: int = 25) -> JsonObject:
        self.calls.append(("domain_references", domain_query, limit))
        return {"method": "domain_references", "domain": domain_query, "limit": limit}

    def endpoints(self, path_query: str | None = None, limit: int = 25) -> JsonObject:
        self.calls.append(("endpoints", path_query, limit))
        return {"method": "endpoints", "path": path_query, "limit": limit}

    def event_channels(self, channel_query: str | None = None, limit: int = 25) -> JsonObject:
        self.calls.append(("event_channels", channel_query, limit))
        return {"method": "event_channels", "channel": channel_query, "limit": limit}

    def modules_importing(self, package: str, limit: int = 25) -> list[JsonObject]:
        self.calls.append(("modules_importing", package, limit))
        return [{"method": "modules_importing", "package": package, "limit": limit}]

    def repo_dependencies(self, repo: str, limit: int = 25) -> JsonObject:
        self.calls.append(("repo_dependencies", repo, limit))
        return {"method": "repo_dependencies", "repo": repo, "limit": limit}

    def lookup_symbol(self, symbol_query: str, limit: int = 25) -> JsonObject:
        self.calls.append(("lookup_symbol", symbol_query, limit))
        return {"method": "lookup_symbol", "query": symbol_query, "limit": limit}


if __name__ == "__main__":
    unittest.main()
