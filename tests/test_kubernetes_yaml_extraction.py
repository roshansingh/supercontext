from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ConfigKgBuild, ScannedFile
from source.kg.file_formats.kubernetes_yaml import extract_kubernetes_manifests


class KubernetesYamlExtractionTest(unittest.TestCase):
    def test_deployment_service_ingress_emits_service_deploy_and_domain_route(self) -> None:
        build = _extract(
            "deployment/kubernetes/staging/api/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders-api\n"
            "  namespace: production\n"
            "spec:\n"
            "  selector:\n"
            "    matchLabels:\n"
            "      app: orders-api\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: orders-api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: orders-api\n"
            "        image: registry.example.com/acme/orders_api:sha\n"
            "---\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: orders-api-service\n"
            "  namespace: production\n"
            "spec:\n"
            "  selector:\n"
            "    app: orders-api\n"
            "  ports:\n"
            "  - port: 80\n"
            "    targetPort: 8000\n"
            "---\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: orders-ingress\n"
            "  namespace: production\n"
            "spec:\n"
            "  rules:\n"
            "  - host: orders.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - path: /\n"
            "        backend:\n"
            "          service:\n"
            "            name: orders-api-service\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_entity_count(build, "Domain"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)
        deploy = next(fact for fact in build.facts if fact.predicate == "DEPLOYS_VIA_CONFIG")
        route = next(fact for fact in build.facts if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertEqual(deploy.object_id, route.object_id)
        self.assertEqual(deploy.qualifier["source_kind"], "kubernetes_manifest")
        self.assertEqual(deploy.qualifier["target_type"], "kubernetes_deployment")
        self.assertEqual(deploy.qualifier["namespace"], "production")
        self.assertEqual(deploy.qualifier["workload"], "orders-api")
        self.assertEqual(route.qualifier["backend_service"], "orders-api-service")
        self.assertEqual(route.qualifier["backend_service_ports"], [{"port": 80, "targetPort": 8000}])
        self.assertEqual(route.qualifier["match_basis"], "ingress_backend_service_selector_to_workload")

    def test_service_port_and_node_port_require_integers_but_target_port_may_be_named(self) -> None:
        build = _extract(
            "deployment/kubernetes/staging/api/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders-api\n"
            "spec:\n"
            "  selector:\n"
            "    matchLabels:\n"
            "      app: orders-api\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: orders-api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: orders-api\n"
            "        image: registry.example.com/acme/orders_api:sha\n"
            "---\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: orders-api-service\n"
            "spec:\n"
            "  selector:\n"
            "    app: orders-api\n"
            "  ports:\n"
            "  - port: http\n"
            "    targetPort: http\n"
            "    nodePort: external\n"
            "  - targetPort: metrics\n"
            "---\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: orders-ingress\n"
            "spec:\n"
            "  rules:\n"
            "  - host: orders.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - backend:\n"
            "          service:\n"
            "            name: orders-api-service\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        route = next(fact for fact in build.facts if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertEqual(route.qualifier["backend_service_ports"], [{"targetPort": "http"}, {"targetPort": "metrics"}])
        self.assertEqual(
            {row.scope_ref["reason"] for row in build.coverage},
            {
                "kubernetes_service_node_port_malformed",
                "kubernetes_service_port_malformed",
                "kubernetes_service_port_missing",
            },
        )
        self.assertEqual({row.predicate for row in build.coverage}, {"ROUTES_DOMAIN_TO_DEPLOY"})
        self.assertEqual({row.scope_ref["service_name"] for row in build.coverage}, {"orders-api-service"})

    def test_unowned_workload_does_not_emit_service_deploy_fact(self) -> None:
        build = _extract(
            "manifests/payments.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: payments-api\n"
            "spec:\n"
            "  selector:\n"
            "    matchLabels:\n"
            "      app: payments-api\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: payments-api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: payments-api\n"
            "        image: registry.example.com/acme/payments-api:sha\n",
            repo_name="platform_manifests",
            service_slug="platform-manifests",
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)

    def test_registry_port_image_still_contributes_image_repo_ownership(self) -> None:
        build = _extract(
            "k8s/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: worker\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: worker\n"
            "        image: registry.example.com:5000/team/orders_api\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)

    def test_workload_name_overlap_without_image_match_does_not_claim_ownership(self) -> None:
        build = _extract(
            "k8s/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: worker\n"
            "        image: registry.example.com/team/orders-pipeline:sha\n",
            repo_name="orders",
            service_slug="orders",
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)

    def test_short_common_service_token_does_not_claim_unrelated_workload(self) -> None:
        build = _extract(
            "k8s/gateway.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: gateway\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: api\n"
            "        image: registry.example.com/team/api-gateway:sha\n",
            repo_name="api",
            service_slug="api",
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)

    def test_ingress_requires_service_selector_link_to_route_domain_to_workload(self) -> None:
        build = _extract(
            "k8s/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders-api\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: orders-api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: orders-api\n"
            "        image: orders_api:latest\n"
            "---\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: orders-api-service\n"
            "spec:\n"
            "  selector:\n"
            "    app: different-api\n"
            "---\n"
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: orders-ingress\n"
            "spec:\n"
            "  rules:\n"
            "  - host: orders.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - backend:\n"
            "          service:\n"
            "            name: orders-api-service\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)

    def test_legacy_ingress_backend_service_name_is_supported(self) -> None:
        build = _extract(
            "k8s/orders.yaml",
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders-api\n"
            "spec:\n"
            "  template:\n"
            "    metadata:\n"
            "      labels:\n"
            "        app: orders-api\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: orders-api\n"
            "        image: orders_api:latest\n"
            "---\n"
            "apiVersion: v1\n"
            "kind: Service\n"
            "metadata:\n"
            "  name: orders-api-service\n"
            "spec:\n"
            "  selector:\n"
            "    app: orders-api\n"
            "---\n"
            "apiVersion: extensions/v1beta1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: orders-ingress\n"
            "spec:\n"
            "  rules:\n"
            "  - host: orders.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - backend:\n"
            "          serviceName: orders-api-service\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cronjob_emits_kubernetes_cronjob_deploy_target(self) -> None:
        build = _extract(
            "kubernetes/jobs/sync.yaml",
            "apiVersion: batch/v1\n"
            "kind: CronJob\n"
            "metadata:\n"
            "  name: orders-api-sync\n"
            "spec:\n"
            "  jobTemplate:\n"
            "    spec:\n"
            "      template:\n"
            "        spec:\n"
            "          containers:\n"
            "          - name: orders-api\n"
            "            image: registry.example.com/orders_api:sha\n",
            repo_name="orders_api",
            service_slug="orders-api",
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        deploy = next(fact for fact in build.facts if fact.predicate == "DEPLOYS_VIA_CONFIG")
        self.assertEqual(deploy.qualifier["target_type"], "kubernetes_cron_job")
        self.assertEqual(deploy.qualifier["kubernetes_kind"], "CronJob")

    def test_non_kubernetes_yaml_is_skipped(self) -> None:
        build = _extract("config.yml", "name: ordinary-config\nvalue: true\n")

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(build.coverage, [])

    def test_non_kubernetes_crd_workload_like_yaml_is_skipped(self) -> None:
        build = _extract(
            "k8s/pipeline.yaml",
            "apiVersion: tekton.dev/v1\n"
            "kind: Pipeline\n"
            "metadata:\n"
            "  name: orders-api\n"
            "spec:\n"
            "  tasks: []\n",
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(build.coverage, [])

    def test_known_kind_with_unknown_api_group_is_skipped(self) -> None:
        build = _extract(
            "k8s/custom.yaml",
            "apiVersion: example.com/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: orders-api\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: orders-api\n"
            "        image: orders_api:latest\n",
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(build.coverage, [])

    def test_likely_kubernetes_parse_error_emits_coverage(self) -> None:
        build = _extract("kubernetes/bad.yaml", "apiVersion: [not valid yaml\n")

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(len(build.coverage), 1)
        self.assertEqual(build.coverage[0].predicate, "DEPLOYS_VIA_CONFIG")
        self.assertEqual(build.coverage[0].scope_ref["reason"], "kubernetes_yaml_parse_error")

    def test_non_kubernetes_deployment_doc_parse_error_does_not_emit_coverage(self) -> None:
        build = _extract("docs/deployment-guide.yaml", "apiVersion: [not valid yaml\n")

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(build.coverage, [])

    def test_yaml_without_manifest_header_is_not_parsed_as_kubernetes(self) -> None:
        build = _extract(
            "k8s/generated.yaml",
            "name: orders\n"
            "settings:\n"
            "  kind: Deployment\n"
            "  apiVersion: apps/v1\n",
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])
        self.assertEqual(build.coverage, [])


def _extract(
    relative_path: str,
    text: str,
    *,
    repo_name: str = "orders_api",
    service_slug: str = "orders-api",
) -> ConfigKgBuild:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name=repo_name,
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (), "typescript": ()},
        )
        scanned = ScannedFile(path=path, relative_path=relative_path, text=text, lines=tuple(text.splitlines()))
        service = Entity(
            kind="Service",
            identity={"tenant_id": "default", "namespace": "default", "repo": repo_name, "slug": service_slug},
        )
        build = ConfigKgBuild()
        extract_kubernetes_manifests(repo, scanned, service, build, "default")
        return build


def _entity_count(build: ConfigKgBuild, kind: str) -> int:
    return len([entity for entity in build.entities if entity.kind == kind])


def _fact_count(build: ConfigKgBuild, predicate: str) -> int:
    return len([fact for fact in build.facts if fact.predicate == predicate])


if __name__ == "__main__":
    unittest.main()
