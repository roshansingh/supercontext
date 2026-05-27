from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.store import JsonlKgStore
from source.kg.product.mcp_tools import call_tool
from source.kg.query.snapshot import KgSnapshot


class OwnershipContextTest(unittest.TestCase):
    def test_package_author_is_candidate_not_proven_owner(self) -> None:
        with _ownership_snapshot(
            {
                "pyproject.toml": """
[project]
name = "checkout-api"
authors = [{name = "Package Author", email = "author@example.com"}]
""".lstrip()
            }
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["answer_packet"]["service_identity"]["slug"], "checkout-api")
        self.assertEqual(ownership["status"], "partial")
        self.assertEqual(ownership["missing_fact_families"], ["service_ownership"])
        self.assertFalse(ownership["answer_packet"]["can_answer_owner"])
        self.assertIsNone(ownership["answer_packet"]["proven_owner"])
        self.assertEqual(ownership["candidate_maintainers"][0]["candidate"], "Package Author <author@example.com>")
        self.assertFalse(ownership["candidate_maintainers"][0]["promotion_allowed"])
        self.assertIn("not service ownership", ownership["candidate_maintainers"][0]["promotion_blocked_reason"])

    def test_catalog_owner_is_proven_owner(self) -> None:
        with _ownership_snapshot(
            {
                "catalog-info.yaml": """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: checkout-api
spec:
  type: service
  owner: platform-team
""".lstrip(),
                "service.yml": "owner: duplicate-team\n",
                "pyproject.toml": """
[project]
name = "checkout-api"
authors = [{name = "Package Author"}]
""".lstrip(),
            }
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["status"], "answerable")
        self.assertEqual(ownership["missing_fact_families"], [])
        self.assertTrue(ownership["answer_packet"]["can_answer_owner"])
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["owners"], ["platform-team"])
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["source_kind"], "service_catalog")
        self.assertEqual(len(ownership["proven_owners"]), 1)
        self.assertEqual(ownership["candidate_maintainers"][0]["candidate"], "Package Author")

    def test_codeowners_owner_is_proven_and_comments_are_ignored(self) -> None:
        with _ownership_snapshot(
            {
                "CODEOWNERS": "# no usable owners here\n/bad @ foo@\n",
                ".github/CODEOWNERS": """
# service owners
/services/checkout @platform/checkout-team # primary owner
/bad @ foo@
""".lstrip(),
                "docs/CODEOWNERS": "/ignored @other/team\n",
                "package.json": """
{
  "name": "checkout-api",
  "author": "Package Author <author@example.com>"
}
""".lstrip(),
            }
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["status"], "answerable")
        self.assertTrue(ownership["answer_packet"]["can_answer_owner"])
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["owners"], ["@platform/checkout-team"])
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["source_kind"], "codeowners")
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["scope_pattern"], "/services/checkout")
        self.assertEqual(len(ownership["proven_owners"]), 1)
        self.assertEqual(ownership["candidate_maintainers"][0]["candidate"], "Package Author <author@example.com>")
        self.assertFalse(ownership["candidate_maintainers"][0]["promotion_allowed"])

    def test_manifest_relative_repo_path_is_resolved_from_snapshot_root(self) -> None:
        with _ownership_snapshot(
            {
                "catalog-info.yaml": """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: checkout-api
spec:
  type: service
  owner: platform-team
""".lstrip()
            },
            relative_manifest_path=True,
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["status"], "answerable")
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["owners"], ["platform-team"])

    def test_generic_service_yaml_top_level_owner_is_not_proven_owner(self) -> None:
        with _ownership_snapshot(
            {
                "service.yml": "owner: platform-team\n",
                "pyproject.toml": """
[project]
name = "checkout-api"
authors = [{name = ""}]
""".lstrip(),
            }
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["status"], "partial")
        self.assertFalse(ownership["answer_packet"]["can_answer_owner"])
        self.assertEqual(ownership["proven_owners"], [])
        self.assertEqual(ownership["candidate_maintainers"], [])

    def test_catalog_shaped_service_yaml_spec_owner_is_proven_owner(self) -> None:
        with _ownership_snapshot(
            {
                "service.yml": """
apiVersion: backstage.io/v1alpha1
kind: Component
spec:
  owner: platform-team
""".lstrip()
            }
        ) as kg:
            result = call_tool(kg, "planning_context", {"repo": "checkout-api"})

        ownership = result["ownership_context"]
        self.assertEqual(ownership["status"], "answerable")
        self.assertEqual(ownership["answer_packet"]["proven_owner"]["owners"], ["platform-team"])

    def test_snapshot_rejects_malformed_manifest_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl"):
                (root / filename).write_text("", encoding="utf-8")
            (root / "manifest.json").write_text("{not json", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Invalid KG manifest JSON"):
                KgSnapshot(root)


class _ownership_snapshot:
    def __init__(self, files: dict[str, str], *, relative_manifest_path: bool = False) -> None:
        self.files = files
        self.relative_manifest_path = relative_manifest_path

    def __enter__(self) -> KgSnapshot:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        snapshot_root = root / "snapshot"
        repo_root = snapshot_root / "repo" if self.relative_manifest_path else root / "repo"
        repo_root.mkdir(parents=True)
        for relative, content in self.files.items():
            path = repo_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        manifest_repo_path = "repo" if self.relative_manifest_path else str(repo_root)
        service = Entity(
            kind="Service",
            identity={"tenant_id": "default", "namespace": "default", "repo": "checkout-api", "slug": "checkout-api"},
            properties={"repo": "checkout-api"},
        )
        JsonlKgStore(snapshot_root).write(
            entities=[service],
            facts=[],
            evidence=[],
            coverage=[],
            manifest={
                "counts": {"entities": 1, "facts": 0},
                "repos": [{"repo_name": "checkout-api", "repo_path": manifest_repo_path}],
            },
        )
        self._kg = KgSnapshot(snapshot_root)
        return self._kg

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
