from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.python.package_resolver import PythonPackageResolver


class PythonPackageResolverTest(unittest.TestCase):
    def test_pyproject_metadata_uses_project_name_and_poetry_package_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "pyproject.toml").write_text(
                '[project]\n'
                'name = "acme-service"\n'
                "\n"
                "[tool.poetry]\n"
                'packages = [{include = "acme_service"}]\n',
                encoding="utf-8",
            )

            metadata = PythonPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "acme-service")
            self.assertEqual(metadata.manifest_path, repo / "pyproject.toml")
            self.assertGreaterEqual(metadata.aliases, {"acme-service", "repo", "acme_service"})

    def test_setup_cfg_metadata_uses_declared_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "setup.cfg").write_text("[metadata]\nname = shared-pkg\n", encoding="utf-8")

            metadata = PythonPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "shared-pkg")
            self.assertEqual(metadata.aliases, frozenset({"shared-pkg", "repo"}))

    def test_setup_py_metadata_uses_literal_setup_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "setup.py").write_text("from setuptools import setup\nsetup(name='shared-pkg')\n", encoding="utf-8")

            metadata = PythonPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "shared-pkg")

    def test_package_metadata_rejects_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "setup.cfg").mkdir()

            with self.assertRaisesRegex(ValueError, "Package manifest path is not a file"):
                PythonPackageResolver().package_metadata(_repo_snapshot(repo))

    def test_resolve_uses_known_import_root_distribution_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "sklearn-provider"
            repo.mkdir(parents=True)
            (repo / "pyproject.toml").write_text('[project]\nname = "scikit-learn"\n', encoding="utf-8")

            resolved = PythonPackageResolver().resolve("sklearn", [_repo_snapshot(repo)])

            self.assertEqual(resolved, "scikit-learn")

    def test_resolve_fails_closed_on_ambiguous_provider_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "owner-a" / "provider-a"
            second = Path(tmpdir) / "owner-b" / "provider-b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "pyproject.toml").write_text('[project]\nname = "shared-pkg"\n', encoding="utf-8")
            (second / "pyproject.toml").write_text('[project]\nname = "shared-pkg"\n', encoding="utf-8")

            resolved = PythonPackageResolver().resolve("shared_pkg", [_repo_snapshot(first), _repo_snapshot(second)])

            self.assertIsNone(resolved)


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


if __name__ == "__main__":
    unittest.main()
