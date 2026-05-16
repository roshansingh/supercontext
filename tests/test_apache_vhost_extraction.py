from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.apache_vhost import extract_apache_vhost_routes
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile


class ApacheVhostExtractionTest(unittest.TestCase):
    def test_single_vhost_emits_domain_to_deploy_mapping(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  ServerName api.example.com\n"
            "  WSGIScriptAlias / /srv/app/wsgi.py\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(_entity_count(build, "Domain"), 1)
        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)
        route = next(fact for fact in build.facts if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertEqual(route.qualifier, {"source_kind": "apache_vhost"})
        self.assertEqual(_deploy_targets(build), ["/srv/app/wsgi.py"])

    def test_server_alias_emits_routes_for_each_alias(self) -> None:
        build = _extract(
            "<VirtualHost *:443>\n"
            "  ServerName api.example.com\n"
            "  ServerAlias api2.example.com api3.example.com\n"
            "  WSGIScriptAlias / /srv/app/wsgi.py\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(sorted(_domains(build)), ["api.example.com", "api2.example.com", "api3.example.com"])
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 3)

    def test_multiple_blocks_are_independent(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  ServerName one.example.com\n"
            "  WSGIScriptAlias / /srv/one/wsgi.py\n"
            "</VirtualHost>\n"
            "<VirtualHost *:80>\n"
            "  ServerName two.example.com\n"
            "  WSGIScriptAlias / /srv/two/wsgi.py\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(sorted(_domains(build)), ["one.example.com", "two.example.com"])
        self.assertEqual(sorted(_deploy_targets(build)), ["/srv/one/wsgi.py", "/srv/two/wsgi.py"])
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 2)

    def test_wsgiscriptalias_without_domain_emits_no_facts(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  WSGIScriptAlias / /srv/app/wsgi.py\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_server_name_without_wsgiscriptalias_emits_no_facts(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  ServerName api.example.com\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_comments_and_trailing_comments_are_ignored(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  # ServerName ignored.example.com\n"
            "  ServerName api.example.com # primary host\n"
            "  WSGIScriptAlias / /srv/app/wsgi.py # deploy target\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])
        self.assertEqual(_deploy_targets(build), ["/srv/app/wsgi.py"])

    def test_hash_inside_quoted_value_is_not_treated_as_comment(self) -> None:
        build = _extract(
            "<VirtualHost *:80>\n"
            "  ServerName api.example.com\n"
            "  WSGIScriptAlias / \"/srv/app#blue/wsgi.py\" # deploy target\n"
            "</VirtualHost>\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])
        self.assertEqual(_deploy_targets(build), ["/srv/app#blue/wsgi.py"])

    def test_directives_are_case_insensitive(self) -> None:
        build = _extract(
            "<virtualhost *:80>\n"
            "  servername api.example.com\n"
            "  wsgiscriptalias / /srv/app/wsgi.py\n"
            "</virtualhost>\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])
        self.assertEqual(_deploy_targets(build), ["/srv/app/wsgi.py"])

    def test_directives_outside_vhost_are_ignored(self) -> None:
        build = _extract(
            "ServerName api.example.com\n"
            "WSGIScriptAlias / /srv/app/wsgi.py\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])


def _extract(text: str) -> ConfigKgBuild:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        conf = root / "site.conf"
        conf.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name="deploy-config",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (), "typescript": ()},
        )
        scanned = ScannedFile(path=conf, relative_path="site.conf", text=text, lines=tuple(text.splitlines()))
        service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
        build = ConfigKgBuild()
        extract_apache_vhost_routes(repo, scanned, service, build, "default")
        return build


def _entity_count(build: ConfigKgBuild, kind: str) -> int:
    return len([entity for entity in build.entities if entity.kind == kind])


def _fact_count(build: ConfigKgBuild, predicate: str) -> int:
    return len([fact for fact in build.facts if fact.predicate == predicate])


def _domains(build: ConfigKgBuild) -> list[str]:
    return [entity.identity["name"] for entity in build.entities if entity.kind == "Domain"]


def _deploy_targets(build: ConfigKgBuild) -> list[str]:
    return [entity.identity["target"] for entity in build.entities if entity.kind == "DeployTarget"]


if __name__ == "__main__":
    unittest.main()
