from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.build.multi_repo import build_multi_kg
from source.kg.build.pipeline import build_kg
from source.kg.core.store import read_jsonl
from source.kg.file_formats._shared.common import endpoint_entity, event_channel_entity


class TenantIdThreadingTest(unittest.TestCase):
    def test_single_repo_defaults_to_default_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo(root, "service_a")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": ""}, clear=False):
                manifest = build_kg(repo, out)

            self.assertEqual(manifest["tenant_id"], "default")
            self.assertEqual(_identity_tenants(out), {"default"})
            self.assertEqual(_coverage_tenants(out), {"default"})

    def test_env_tenant_is_used_when_cli_tenant_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo(root, "service_a")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": "tenant-env"}, clear=False):
                manifest = build_kg(repo, out)

            self.assertEqual(manifest["tenant_id"], "tenant-env")
            self.assertEqual(_identity_tenants(out), {"tenant-env"})
            self.assertEqual(_coverage_tenants(out), {"tenant-env"})

    def test_explicit_tenant_overrides_env_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo(root, "service_a")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": "tenant-env"}, clear=False):
                manifest = build_kg(repo, out, tenant_id="tenant-cli")

            self.assertEqual(manifest["tenant_id"], "tenant-cli")
            self.assertEqual(_identity_tenants(out), {"tenant-cli"})
            self.assertEqual(_coverage_tenants(out), {"tenant-cli"})

    def test_multi_repo_defaults_to_default_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = _repo(root, "service_a")
            repo_b = _repo(root, "service_b")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": ""}, clear=False):
                manifest = build_multi_kg([repo_a, repo_b], out)

            self.assertEqual(manifest["tenant_id"], "default")
            self.assertEqual(_identity_tenants(out), {"default"})
            self.assertEqual(_coverage_tenants(out), {"default"})

    def test_multi_repo_uses_env_tenant_when_cli_tenant_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = _repo(root, "service_a")
            repo_b = _repo(root, "service_b")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": "tenant-env"}, clear=False):
                manifest = build_multi_kg([repo_a, repo_b], out)

            self.assertEqual(manifest["tenant_id"], "tenant-env")
            self.assertEqual(_identity_tenants(out), {"tenant-env"})
            self.assertEqual(_coverage_tenants(out), {"tenant-env"})

    def test_multi_repo_explicit_tenant_overrides_env_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = _repo(root, "service_a")
            repo_b = _repo(root, "service_b")
            out = root / "kg"

            with patch.dict("os.environ", {"SUPERCONTEXT_TENANT_ID": "tenant-env"}, clear=False):
                manifest = build_multi_kg([repo_a, repo_b], out, tenant_id="tenant-multi")

            self.assertEqual(manifest["tenant_id"], "tenant-multi")
            self.assertEqual(_identity_tenants(out), {"tenant-multi"})
            self.assertEqual(_coverage_tenants(out), {"tenant-multi"})

    def test_endpoint_entity_preserves_positional_host_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _repo_snapshot(Path(tmpdir))

            endpoint = endpoint_entity(repo, "GET", "/orders", "api.example.com", tenant_id="tenant-cli")

            self.assertEqual(endpoint.identity["tenant_id"], "tenant-cli")
            self.assertEqual(endpoint.identity["host"], "api.example.com")

    def test_event_channel_entity_uses_explicit_keyword_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _repo_snapshot(Path(tmpdir))

            channel = event_channel_entity(repo, "sqs", "orders", tenant_id="tenant-cli")

            self.assertEqual(channel.identity["tenant_id"], "tenant-cli")


def _repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\n',
        encoding="utf-8",
    )
    (repo / "module.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    return repo


def _repo_snapshot(root: Path):
    from source.kg.core.repo_source import RepoSnapshot

    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        files_by_language={"python": (), "typescript": ()},
    )


def _identity_tenants(snapshot_dir: Path) -> set[str]:
    return {
        str(record["identity"]["tenant_id"])
        for record in read_jsonl(snapshot_dir / "entities.jsonl")
        if isinstance(record.get("identity"), dict) and "tenant_id" in record["identity"]
    }


def _coverage_tenants(snapshot_dir: Path) -> set[str]:
    return {str(record["tenant_id"]) for record in read_jsonl(snapshot_dir / "coverage.jsonl")}


if __name__ == "__main__":
    unittest.main()
