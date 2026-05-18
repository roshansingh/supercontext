from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.dotnet.package_resolver import DotnetPackageResolver


class DotnetPackageResolverTest(unittest.TestCase):
    def test_csproj_metadata_uses_package_id_and_declared_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text(
                "<Project>"
                "<PropertyGroup>"
                "<PackageId>Acme.Shared.Package</PackageId>"
                "<AssemblyName>Acme.Shared</AssemblyName>"
                "<RootNamespace>Acme.Shared.Root</RootNamespace>"
                "</PropertyGroup>"
                "</Project>\n",
                encoding="utf-8",
            )

            metadata = DotnetPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "Acme.Shared.Package")
            self.assertEqual(metadata.manifest_path, repo / "Provider.csproj")
            self.assertGreaterEqual(
                metadata.aliases,
                {"provider", "Provider", "Acme.Shared.Package", "Acme.Shared", "Acme.Shared.Root"},
            )

    def test_csproj_metadata_falls_back_to_project_file_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text("<Project />\n", encoding="utf-8")

            metadata = DotnetPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "Provider")
            self.assertEqual(metadata.aliases, frozenset({"provider", "Provider"}))

    def test_csproj_malformed_xml_falls_back_to_project_file_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text("<Project>", encoding="utf-8")

            metadata = DotnetPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "Provider")
            self.assertEqual(metadata.aliases, frozenset({"provider", "Provider"}))

    def test_manifest_paths_ignore_build_output_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text("<Project />\n", encoding="utf-8")
            generated = repo / "obj" / "Debug" / "Generated.csproj"
            generated.parent.mkdir(parents=True)
            generated.write_text("<Project />\n", encoding="utf-8")

            manifest_paths = DotnetPackageResolver().manifest_paths(_repo_snapshot(repo))

            self.assertEqual(manifest_paths, (repo / "Provider.csproj",))

    def test_csproj_metadata_supports_msbuild_xml_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text(
                '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
                "<PropertyGroup><AssemblyName>Acme.Legacy</AssemblyName></PropertyGroup>"
                "</Project>\n",
                encoding="utf-8",
            )

            metadata = DotnetPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "Acme.Legacy")
            self.assertIn("Acme.Legacy", metadata.aliases)

    def test_package_metadata_rejects_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").mkdir()

            with self.assertRaisesRegex(ValueError, "Package manifest path is not a file"):
                DotnetPackageResolver().package_metadata(_repo_snapshot(repo))

    def test_resolve_matches_namespace_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text(
                "<Project><PropertyGroup><RootNamespace>Acme.Shared</RootNamespace></PropertyGroup></Project>\n",
                encoding="utf-8",
            )

            resolved = DotnetPackageResolver().resolve("Acme.Shared.Models", [_repo_snapshot(repo)])

            self.assertEqual(resolved, "Acme.Shared")

    def test_resolve_fails_closed_on_ambiguous_provider_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "owner-a" / "provider-a"
            second = Path(tmpdir) / "owner-b" / "provider-b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            for repo in (first, second):
                (repo / "Provider.csproj").write_text(
                    "<Project><PropertyGroup><RootNamespace>Acme.Shared</RootNamespace></PropertyGroup></Project>\n",
                    encoding="utf-8",
                )

            resolved = DotnetPackageResolver().resolve(
                "Acme.Shared.Models",
                [_repo_snapshot(first), _repo_snapshot(second)],
            )

            self.assertIsNone(resolved)

    def test_repo_snapshot_is_usable_as_resolver_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "Provider.csproj").write_text(
                "<Project><PropertyGroup><AssemblyName>Acme.Shared</AssemblyName></PropertyGroup></Project>\n",
                encoding="utf-8",
            )
            snapshot = _repo_snapshot(repo)
            resolver = DotnetPackageResolver()

            first = resolver.package_metadata(snapshot)
            second = resolver.package_metadata(snapshot)

            self.assertIs(first, second)


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


if __name__ == "__main__":
    unittest.main()
