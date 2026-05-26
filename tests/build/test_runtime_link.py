from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.build.runtime_link import RuntimeLinkerInput, link_runtime_targets
from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.repo_source import RepoSnapshot


class RuntimeLinkTest(unittest.TestCase):
    def test_wsgi_target_resolves_to_unique_service_by_module_path_suffix(self) -> None:
        service = _service("mercury_api")
        module = _module("mercury_api", "mercury_api/prod_wsgi.py")
        target = _deploy_target("ansible-playbooks", "/home/ubuntu/mercury_api/mercury_api/prod_wsgi.py")
        route = Fact("ROUTES_DOMAIN_TO_DEPLOY", _domain("ansible-playbooks", "api.example.com").entity_id, target.entity_id)
        result = link_runtime_targets(
            (
                _input("ansible-playbooks", (target,), (route,), (_evidence_for(target),)),
                _input("mercury_api", (service, module)),
            )
        )

        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].predicate, "DEPLOYS_VIA_CONFIG")
        self.assertEqual(result.facts[0].subject_id, service.entity_id)
        self.assertEqual(result.facts[0].object_id, target.entity_id)
        self.assertEqual(result.evidence[0].bytes_ref["path"], "apache/site.conf")

    def test_wsgi_target_ambiguous_suffix_emits_no_link(self) -> None:
        target = _deploy_target("infra", "/srv/apps/app/wsgi.py")
        result = link_runtime_targets(
            (
                _input("infra", (target,), evidence=(_evidence_for(target),)),
                _input("api-a", (_service("api-a"), _module("api-a", "app/wsgi.py"))),
                _input("api-b", (_service("api-b"), _module("api-b", "app/wsgi.py"))),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.ambiguous_link_count, 1)
        self.assertIn("ambiguous_wsgi_module_suffix", {row.scope_ref["reason"] for row in result.coverage})

    def test_wsgi_target_rejects_basename_only_suffix(self) -> None:
        target = _deploy_target("infra", "/srv/apps/api/wsgi.py")
        result = link_runtime_targets(
            (
                _input("infra", (target,), evidence=(_evidence_for(target),)),
                _input("api", (_service("api"), _module("api", "wsgi.py"))),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertIn("no_wsgi_module_match", {row.scope_ref["reason"] for row in result.coverage})

    def test_wsgi_target_rejects_cross_tenant_match(self) -> None:
        target = _deploy_target("infra", "/srv/apps/api/app/wsgi.py", tenant_id="tenant-a")
        result = link_runtime_targets(
            (
                _input("infra", (target,), evidence=(_evidence_for(target),)),
                _input("api", (_service("api", tenant_id="tenant-b"), _module("api", "app/wsgi.py", tenant_id="tenant-b"))),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertIn("no_wsgi_module_match", {row.scope_ref["reason"] for row in result.coverage})

    def test_duplicate_service_entity_from_multiple_extractors_does_not_create_ambiguity(self) -> None:
        service = _service("api")
        target = _deploy_target("infra", "/srv/apps/api/app/wsgi.py")
        result = link_runtime_targets(
            (
                _input("infra", (target,), evidence=(_evidence_for(target),)),
                _input("api", (service, service, _module("api", "app/wsgi.py"))),
            )
        )

        self.assertEqual(len(result.facts), 1)

    def test_wsgi_target_without_coordinate_evidence_emits_no_link(self) -> None:
        target = _deploy_target("infra", "/srv/apps/api/app/wsgi.py")
        result = link_runtime_targets(
            (
                _input("infra", (target,), evidence=(_evidence_without_bytes_for(target),)),
                _input("api", (_service("api"), _module("api", "app/wsgi.py"))),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.evidence, ())
        self.assertIn("no_target_bytes_ref_evidence", {row.scope_ref["reason"] for row in result.coverage})

    def test_zappa_lambda_target_is_handled_by_direct_extractor_not_cross_repo_linker(self) -> None:
        service = _service("api")
        target = _deploy_target("api", "prod:api.app", target_type="zappa_lambda")
        deploy_fact = Fact("DEPLOYS_VIA_CONFIG", service.entity_id, target.entity_id)
        result = link_runtime_targets(
            (
                _input("api", (service, target), (deploy_fact,), (_evidence_for(target),)),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.ambiguous_link_count, 0)
        self.assertNotIn("unsupported_deploy_target_type", {row.scope_ref["reason"] for row in result.coverage})

    def test_kubernetes_target_is_handled_by_direct_extractor_not_cross_repo_linker(self) -> None:
        service = _service("api")
        target = _deploy_target(
            "api",
            "deployment/kubernetes/staging/api.yaml#default/deployment/api",
            target_type="kubernetes_deployment",
        )
        deploy_fact = Fact("DEPLOYS_VIA_CONFIG", service.entity_id, target.entity_id)
        result = link_runtime_targets(
            (
                _input("api", (service, target), (deploy_fact,), (_evidence_for(target),)),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.ambiguous_link_count, 0)
        self.assertNotIn("unsupported_deploy_target_type", {row.scope_ref["reason"] for row in result.coverage})

    def test_cloudfront_target_is_handled_by_direct_extractor_not_cross_repo_linker(self) -> None:
        service = _service("infra")
        target = _deploy_target(
            "infra",
            "cloudfront.tf#aws_cloudfront_distribution.site",
            target_type="cloudfront_distribution",
        )
        deploy_fact = Fact("DEPLOYS_VIA_CONFIG", service.entity_id, target.entity_id)
        result = link_runtime_targets(
            (
                _input("infra", (service, target), (deploy_fact,), (_evidence_for(target),)),
            )
        )

        self.assertEqual(result.facts, ())
        self.assertEqual(result.ambiguous_link_count, 0)
        self.assertNotIn("unsupported_deploy_target_type", {row.scope_ref["reason"] for row in result.coverage})


def _input(
    repo_name: str,
    entities: tuple[Entity, ...],
    facts: tuple[Fact, ...] = (),
    evidence: tuple[Evidence, ...] = (),
) -> RuntimeLinkerInput:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / repo_name
        root.mkdir()
        repo = RepoSnapshot(root, repo_name, "owner", "sha", {})
        return RuntimeLinkerInput(repo, entities, facts, evidence)


def _service(repo: str, *, tenant_id: str = "default") -> Entity:
    return Entity(
        "Service",
        {"tenant_id": tenant_id, "namespace": "default", "repo": repo, "slug": repo},
        {"repo": repo},
    )


def _module(repo: str, path: str, *, tenant_id: str = "default") -> Entity:
    return Entity(
        "CodeModule",
        {"tenant_id": tenant_id, "repo": repo, "module": path.removesuffix(".py").replace("/", ".")},
        {"path": path},
    )


def _deploy_target(repo: str, target: str, *, tenant_id: str = "default", target_type: str = "wsgi") -> Entity:
    return Entity("DeployTarget", {"tenant_id": tenant_id, "repo": repo, "type": target_type, "target": target})


def _domain(repo: str, name: str, *, tenant_id: str = "default") -> Entity:
    return Entity("Domain", {"tenant_id": tenant_id, "repo": repo, "name": name})


def _evidence_for(entity: Entity) -> Evidence:
    return Evidence(
        target_type="entity",
        target_id=entity.entity_id,
        derivation_class="deterministic_static",
        source_system="static_config_v0",
        source_ref={"entity_kind": entity.kind},
        bytes_ref={"repo": "infra", "commit_sha": "sha", "path": "apache/site.conf", "line_start": 7, "line_end": 8},
        confidence=1.0,
    )


def _evidence_without_bytes_for(entity: Entity) -> Evidence:
    return Evidence(
        target_type="entity",
        target_id=entity.entity_id,
        derivation_class="deterministic_static",
        source_system="static_config_v0",
        source_ref={"entity_kind": entity.kind},
        bytes_ref=None,
        confidence=1.0,
    )


if __name__ == "__main__":
    unittest.main()
