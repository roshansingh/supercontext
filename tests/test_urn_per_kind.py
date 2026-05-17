from __future__ import annotations

import unittest

from source.kg.core.models import Entity, stable_hash, urn_for_kind
from source.kg.metrics.compute import _looks_like_hash_urn


class PerKindUrnTest(unittest.TestCase):
    def test_current_v1_entity_kinds_have_non_hash_urn_templates(self) -> None:
        cases = (
            ("Repo", {"tenant_id": "tenant-a", "host": "local", "owner": "org", "name": "repo"}),
            ("Service", {"tenant_id": "tenant-a", "namespace": "default", "repo": "repo", "slug": "api"}),
            ("CodeModule", {"tenant_id": "tenant-a", "repo": "repo", "module": "app.main"}),
            (
                "CodeSymbol",
                {
                    "tenant_id": "tenant-a",
                    "repo": "repo",
                    "module": "app.main",
                    "qualname": "handler",
                    "symbol_kind": "function",
                },
            ),
            ("ExternalPackage", {"tenant_id": "tenant-a", "repo": "repo", "name": "requests"}),
            (
                "Endpoint",
                {
                    "tenant_id": "tenant-a",
                    "repo": "repo",
                    "protocol": "http",
                    "method": "GET",
                    "path": "/health",
                    "host": None,
                },
            ),
            ("Domain", {"tenant_id": "tenant-a", "repo": "repo", "name": "example.com"}),
            ("EnvVar", {"tenant_id": "tenant-a", "repo": "repo", "name": "API_KEY"}),
            ("EventChannel", {"tenant_id": "tenant-a", "broker_kind": "sqs", "channel_address": "orders"}),
            ("DeployTarget", {"tenant_id": "tenant-a", "repo": "repo", "type": "domain", "target": "api.example.com"}),
        )

        for kind, identity in cases:
            with self.subTest(kind=kind):
                self.assertFalse(_looks_like_hash_urn(Entity(kind, identity).urn))

    def test_service_urn_is_human_readable_and_entity_id_is_unchanged(self) -> None:
        identity = {
            "tenant_id": "tenant-a",
            "namespace": "default",
            "repo": "payments-api",
            "slug": "payments",
        }
        entity = Entity("Service", identity)

        self.assertEqual(entity.entity_id, f"ent_{stable_hash('Service', identity)}")
        self.assertEqual(entity.urn, "supercontext://service/tenant-a/default/payments-api/payments")
        self.assertFalse(_looks_like_hash_urn(entity.urn))

    def test_service_urn_distinguishes_repo_for_shared_slug(self) -> None:
        base_identity = {
            "tenant_id": "tenant-a",
            "namespace": "default",
            "slug": "shared-package",
        }

        service_a = Entity("Service", {**base_identity, "repo": "repo-a"})
        service_b = Entity("Service", {**base_identity, "repo": "repo-b"})

        self.assertNotEqual(service_a.entity_id, service_b.entity_id)
        self.assertNotEqual(service_a.urn, service_b.urn)

    def test_code_symbol_urn_uses_current_identity_fields(self) -> None:
        entity = Entity(
            "CodeSymbol",
            {
                "tenant_id": "tenant-a",
                "repo": "api",
                "module": "orders.handlers",
                "qualname": "OrderHandler.create",
                "symbol_kind": "method",
            },
        )

        self.assertEqual(
            entity.urn,
            "supercontext://code-symbol/tenant-a/api/orders.handlers/OrderHandler.create/method",
        )

    def test_code_symbol_urn_distinguishes_symbol_kind(self) -> None:
        base_identity = {
            "tenant_id": "tenant-a",
            "repo": "api",
            "module": "orders",
            "qualname": "Order.status",
        }

        method = Entity("CodeSymbol", {**base_identity, "symbol_kind": "method"})
        property_ = Entity("CodeSymbol", {**base_identity, "symbol_kind": "property"})

        self.assertNotEqual(method.urn, property_.urn)

    def test_endpoint_urn_escapes_path_without_losing_method_or_host(self) -> None:
        entity = Entity(
            "Endpoint",
            {
                "tenant_id": "tenant-a",
                "repo": "api",
                "protocol": "http",
                "method": "GET",
                "path": "/v1/orders/{id}",
                "host": "api.example.com",
            },
        )

        self.assertEqual(
            entity.urn,
            "supercontext://endpoint/tenant-a/api/http/GET/api.example.com/%2Fv1%2Forders%2F%7Bid%7D",
        )

    def test_endpoint_empty_host_uses_none_host_placeholder(self) -> None:
        base_identity = {
            "tenant_id": "tenant-a",
            "repo": "api",
            "protocol": "http",
            "method": "GET",
            "path": "/health",
        }

        none_host = Entity("Endpoint", {**base_identity, "host": None})
        empty_host = Entity("Endpoint", {**base_identity, "host": ""})

        self.assertEqual(none_host.urn, empty_host.urn)
        self.assertEqual(none_host.urn, "supercontext://endpoint/tenant-a/api/http/GET/_/%2Fhealth")

    def test_unknown_kind_falls_back_to_hash_urn(self) -> None:
        identity = {"tenant_id": "tenant-a", "name": "custom"}

        self.assertEqual(urn_for_kind("CustomThing", identity), f"supercontext://customthing/{stable_hash(identity)}")

    def test_supported_kind_with_missing_identity_field_falls_back_to_hash_urn(self) -> None:
        entity = Entity("Service", {"tenant_id": "tenant-a", "namespace": "default"})

        self.assertTrue(_looks_like_hash_urn(entity.urn))


if __name__ == "__main__":
    unittest.main()
