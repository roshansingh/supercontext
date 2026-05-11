from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile


def _load_apache_vhost_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "private-goldset" / "extractors" / "apache_vhost.py"
    spec = importlib.util.spec_from_file_location("private_goldset_apache_vhost", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateGoldsetApacheVhostTest(unittest.TestCase):
    def test_private_apache_extension_emits_domain_to_deploy_mapping(self) -> None:
        module = _load_apache_vhost_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            conf_path = root / "site.conf"
            conf_path.write_text(
                "<VirtualHost *:80>\n"
                "  ServerName api.example.com\n"
                "  WSGIScriptAlias / /home/ubuntu/service/service/wsgi.py\n"
                "</VirtualHost>\n",
                encoding="utf-8",
            )
            text = conf_path.read_text(encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="deploy-config",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )
            scanned = ScannedFile(path=conf_path, relative_path="site.conf", text=text, lines=tuple(text.splitlines()))
            service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
            build = ConfigKgBuild()

            module.extract_apache_vhost_routes(repo, scanned, service, build, "default")

        entities_by_kind = {}
        for entity in build.entities:
            entities_by_kind.setdefault(entity.kind, []).append(entity)
        self.assertEqual(len(entities_by_kind["Domain"]), 1)
        self.assertEqual(len(entities_by_kind["DeployTarget"]), 1)
        self.assertEqual(entities_by_kind["Domain"][0].identity["name"], "api.example.com")
        self.assertEqual(entities_by_kind["DeployTarget"][0].identity["target"], "/home/ubuntu/service/service/wsgi.py")

        facts_by_predicate = {}
        for fact in build.facts:
            facts_by_predicate.setdefault(fact.predicate, []).append(fact)
        self.assertEqual(len(facts_by_predicate["REFERENCES_DOMAIN"]), 1)
        self.assertEqual(len(facts_by_predicate["ROUTES_DOMAIN_TO_DEPLOY"]), 1)
        route_fact = facts_by_predicate["ROUTES_DOMAIN_TO_DEPLOY"][0]
        self.assertEqual(route_fact.qualifier["source_kind"], "apache_vhost")
        self.assertEqual(route_fact.qualifier["target_repo_hint"], "service")


if __name__ == "__main__":
    unittest.main()
