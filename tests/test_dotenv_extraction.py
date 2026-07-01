from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ScannedFile, is_dotenv_file, scan_config_files
from source.kg.file_formats.dotenv import parse_dotenv_assignment
from source.kg.file_formats._shared.static_config import StaticConfigExtractor


class DotenvExtractionTest(unittest.TestCase):
    def test_parse_dotenv_assignment_handles_export_quotes_and_comments(self) -> None:
        cases = {
            "export API_URL='https://api.example.com/v1' # ignored": ("API_URL", "https://api.example.com/v1"),
            'WS_HOST="ws.example.com"': ("WS_HOST", "ws.example.com"),
            "WS_URL=wss://stream.example.com/socket": ("WS_URL", "wss://stream.example.com/socket"),
            "EMPTY_VALUE=": ("EMPTY_VALUE", ""),
            "MULTI_EQUALS=a=b=c": ("MULTI_EQUALS", "a=b=c"),
            " SPACED_KEY = spaced value ": ("SPACED_KEY", "spaced value"),
            'QUOTED_SPACE="  value  "': ("QUOTED_SPACE", "value"),
            "ESCAPED_HASH=val\\#ue": ("ESCAPED_HASH", "val#ue"),
            "not a dotenv assignment": None,
            "KEY:value": None,
            "K#EY=value": None,
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(parse_dotenv_assignment(line), expected)

    def test_dotenv_file_detection_excludes_direnv_files(self) -> None:
        self.assertTrue(is_dotenv_file(_scanned(".env")))
        self.assertTrue(is_dotenv_file(_scanned(".env.production")))
        self.assertTrue(is_dotenv_file(_scanned("settings/.env.testing")))
        self.assertFalse(is_dotenv_file(_scanned(".envrc")))
        self.assertFalse(is_dotenv_file(_scanned(".envrc.local")))
        self.assertFalse(is_dotenv_file(_scanned(".environments")))

    def test_config_scan_excludes_direnv_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_URL=https://api.example.com\n", encoding="utf-8")
            (root / ".envrc").write_text("export API_URL=https://direnv.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="dotenv-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            result = scan_config_files(repo)

        self.assertEqual([scanned.relative_path for scanned in result.files], [".env"])

    def test_config_scan_includes_canonical_cname_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "CNAME").write_text("developer.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="docs-site",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            result = scan_config_files(repo)

        self.assertEqual([scanned.relative_path for scanned in result.files], ["CNAME"])

    def test_config_scan_skips_broken_dotenv_symlink_with_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prisma = root / "packages" / "prisma"
            prisma.mkdir(parents=True)
            try:
                (prisma / ".env").symlink_to("../../.env")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            (root / "CNAME").write_text("developer.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="calcom-like-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            result = scan_config_files(repo)

        self.assertEqual([scanned.relative_path for scanned in result.files], ["CNAME"])
        rows = [
            row
            for row in result.coverage
            if row.predicate == "CONFIG_SCAN"
            and row.scope_ref.get("reason") == "missing_or_unreadable_config_file"
        ]
        self.assertEqual(len(rows), 1)
        scope = rows[0].scope_ref
        self.assertEqual(scope["repo"], "calcom-like-app")
        self.assertEqual(scope["file_path"], "packages/prisma/.env")
        self.assertEqual(scope["error_type"], "FileNotFoundError")
        self.assertEqual(scope["error_errno"], errno.ENOENT)
        self.assertEqual(scope["error_code"], "ENOENT")
        self.assertNotIn(str(root), str(scope))
        self.assertTrue(scope["path_is_symlink"])
        self.assertFalse(scope["symlink_target_is_absolute"])
        self.assertEqual(scope["symlink_target"], "../../.env")

    def test_config_scan_does_not_store_absolute_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prisma = root / "packages" / "prisma"
            prisma.mkdir(parents=True)
            try:
                (prisma / ".env").symlink_to(root / "missing.env")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            repo = RepoSnapshot(
                root=root,
                name="absolute-symlink-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            result = scan_config_files(repo)

        rows = [
            row
            for row in result.coverage
            if row.predicate == "CONFIG_SCAN"
            and row.scope_ref.get("reason") == "missing_or_unreadable_config_file"
        ]
        self.assertEqual(len(rows), 1)
        scope = rows[0].scope_ref
        self.assertTrue(scope["path_is_symlink"])
        self.assertTrue(scope["symlink_target_is_absolute"])
        self.assertNotIn("symlink_target", scope)
        self.assertNotIn(str(root), str(scope))

    def test_config_scan_does_not_store_windows_absolute_symlink_targets_on_posix(self) -> None:
        for target in ("C:\\Users\\example\\missing.env", "\\\\server\\share\\missing.env"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                prisma = root / "packages" / "prisma"
                prisma.mkdir(parents=True)
                try:
                    (prisma / ".env").symlink_to(target)
                except OSError as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")
                repo = RepoSnapshot(
                    root=root,
                    name="windows-symlink-app",
                    owner="test",
                    commit_sha="sha",
                    files_by_language={"python": (), "typescript": ()},
                )

                result = scan_config_files(repo)

                rows = [
                    row
                    for row in result.coverage
                    if row.predicate == "CONFIG_SCAN"
                    and row.scope_ref.get("reason") == "missing_or_unreadable_config_file"
                ]
                self.assertEqual(len(rows), 1)
                scope = rows[0].scope_ref
                self.assertTrue(scope["path_is_symlink"])
                self.assertTrue(scope["symlink_target_is_absolute"])
                self.assertNotIn("symlink_target", scope)
                self.assertNotIn(target, str(scope))

    def test_config_scan_skips_file_that_fails_during_read_with_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_path = root / ".env"
            env_path.write_text("API_URL=https://api.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="read-failure-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )
            original_read_text = Path.read_text

            def fail_env_read(path: Path, *args: object, **kwargs: object) -> str:
                if path == env_path:
                    raise PermissionError(errno.EACCES, "Permission denied", str(path))
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", fail_env_read):
                result = scan_config_files(repo)

        self.assertEqual(result.files, ())
        rows = [
            row
            for row in result.coverage
            if row.predicate == "CONFIG_SCAN"
            and row.scope_ref.get("reason") == "missing_or_unreadable_config_file"
        ]
        self.assertEqual(len(rows), 1)
        scope = rows[0].scope_ref
        self.assertEqual(scope["file_path"], ".env")
        self.assertEqual(scope["error_type"], "PermissionError")
        self.assertEqual(scope["error_errno"], errno.EACCES)
        self.assertEqual(scope["error_code"], "EACCES")
        self.assertFalse(scope["path_is_symlink"])
        self.assertNotIn(str(root), str(scope))

    def test_static_config_extracts_static_site_cname_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "CNAME").write_text("developer.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="docs-site",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor().extract(repo)

        domain_facts = [fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN"]
        self.assertEqual(len(domain_facts), 1)
        self.assertEqual(domain_facts[0].qualifier["literal"], "developer.example.com")
        self.assertEqual(domain_facts[0].qualifier["source_kind"], "static_site_cname")
        self.assertEqual(domain_facts[0].qualifier["path"], "CNAME")

    def test_static_config_extracts_cname_when_domain_env_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "CNAME").write_text("developer.example.com\n", encoding="utf-8")
            (root / ".env").write_text("API_URL=https://api.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="docs-site",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor(include_domain_env=False).extract(repo)

        domain_facts = [fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN"]
        self.assertEqual(len(domain_facts), 1)
        self.assertEqual(domain_facts[0].qualifier["literal"], "developer.example.com")
        self.assertEqual(domain_facts[0].qualifier["source_kind"], "static_site_cname")

    def test_static_config_extracts_dotenv_without_domain_env_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_URL=https://api.example.com/v1\nLOG_LEVEL=info\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="dotenv-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor().extract(repo)

        domain_facts = [fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN"]
        env_facts = [
            fact
            for fact in build.facts
            if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("reference_kind") == "config_assignment"
        ]
        self.assertEqual(len(domain_facts), 1)
        self.assertEqual(len(env_facts), 2)
        self.assertEqual({fact.qualifier["name"] for fact in env_facts}, {"API_URL", "LOG_LEVEL"})

    def test_secret_like_dotenv_assignment_does_not_surface_safe_literal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_SECRET=https://secret.example.com/token\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="dotenv-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor().extract(repo)

        env_fact = next(
            fact
            for fact in build.facts
            if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("name") == "API_SECRET"
        )
        self.assertEqual(env_fact.qualifier["value_kind"], "secret_like")
        self.assertNotIn("safe_literal", env_fact.qualifier)

    def test_dotenv_host_port_value_emits_domain_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_HOST=api.example.com:443\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="dotenv-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor().extract(repo)

        env_fact = next(
            fact
            for fact in build.facts
            if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("name") == "API_HOST"
        )
        domain_facts = [fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN"]
        self.assertEqual(env_fact.qualifier["value_kind"], "domain")
        self.assertEqual(env_fact.qualifier["safe_literal"], "api.example.com:443")
        self.assertEqual(len(domain_facts), 1)
        self.assertEqual(domain_facts[0].qualifier["literal"], "api.example.com:443")

    def test_source_url_literals_are_distinguished_from_config_runtime_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "settings.py").write_text(
                'EXAMPLE = "https://example.com"\nAPI_URL = "https://api.example.com/v1"\n',
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="source-url-app",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": (), "typescript": ()},
            )

            build = StaticConfigExtractor().extract(repo)

        domain_facts = [
            fact
            for fact in build.facts
            if fact.predicate == "REFERENCES_DOMAIN" and fact.qualifier.get("path") == "settings.py"
        ]
        self.assertTrue(
            any(
                fact.qualifier["literal"] == "https://example.com"
                and fact.qualifier["source_kind"] == "source_domain_literal"
                for fact in domain_facts
            )
        )
        self.assertTrue(
            any(
                fact.qualifier["literal"] == "https://api.example.com/v1"
                and fact.qualifier["source_kind"] == "domain_env"
                for fact in domain_facts
            )
        )


def _scanned(filename: str) -> ScannedFile:
    path = Path(filename)
    return ScannedFile(path=path, relative_path=filename, text="", lines=())


if __name__ == "__main__":
    unittest.main()
