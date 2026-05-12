from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.scripts import streamlit_app


class StreamlitAppImportsTest(unittest.TestCase):
    def test_import_does_not_require_streamlit(self) -> None:
        self.assertTrue(hasattr(streamlit_app, "main"))

    def test_query_specs_are_v1_direct_snapshot_methods(self) -> None:
        self.assertEqual(
            set(streamlit_app.query_specs()),
            {
                "summary",
                "find_callers",
                "modules_importing",
                "top_dependencies",
                "blast_radius",
                "lookup_symbol",
            },
        )

    def test_discover_snapshots_requires_complete_jsonl_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            complete = root / "complete"
            complete.mkdir()
            for filename in streamlit_app.REQUIRED_SNAPSHOT_FILES:
                (complete / filename).write_text("", encoding="utf-8")
            incomplete = root / "incomplete"
            incomplete.mkdir()
            (incomplete / "entities.jsonl").write_text("", encoding="utf-8")
            directory_entry = root / "directory-entry"
            directory_entry.mkdir()
            for filename in streamlit_app.REQUIRED_SNAPSHOT_FILES:
                path = directory_entry / filename
                if filename == "entities.jsonl":
                    path.mkdir()
                else:
                    path.write_text("", encoding="utf-8")

            self.assertEqual(streamlit_app.discover_snapshots(root), [complete])

    def test_org_discovery_uses_supplied_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "org-b" / "repo").mkdir(parents=True)
            (root / "org-a" / "repo").mkdir(parents=True)
            (root / "empty-org").mkdir()
            (root / "README.md").write_text("not an org", encoding="utf-8")

            self.assertEqual(streamlit_app.discover_orgs(root), ["org-a", "org-b"])

    def test_build_hint_uses_org_root_without_private_names(self) -> None:
        hint = streamlit_app.build_multi_kg_hint(
            Path("$SUPERCONTEXT_ORGS_ROOT"),
            Path("$SNAPSHOTS_ROOT"),
            "example-org",
        )
        self.assertIn("$SUPERCONTEXT_ORGS_ROOT/example-org/<repo>", hint)
        self.assertIn("--out $SNAPSHOTS_ROOT/example-org", hint)
        self.assertNotIn("/Users/", hint)

    def test_required_query_args_fail_closed(self) -> None:
        self.assertEqual(streamlit_app._missing_required_arg("find_callers", {"symbol": "  "}), "a symbol")
        self.assertEqual(streamlit_app._missing_required_arg("modules_importing", {"package": ""}), "a package")
        self.assertIsNone(streamlit_app._missing_required_arg("summary", {}))

    def test_resolve_orgs_root_precedence(self) -> None:
        with patch.dict(os.environ, {"SUPERCONTEXT_ORGS_ROOT": "/tmp/from-env"}):
            self.assertEqual(streamlit_app.resolve_orgs_root(), Path("/tmp/from-env"))
            self.assertEqual(streamlit_app.resolve_orgs_root("/tmp/explicit"), Path("/tmp/explicit"))

    def test_main_prints_install_hint_without_streamlit(self) -> None:
        if streamlit_app.streamlit_available():
            self.skipTest("Streamlit is installed in this environment")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            streamlit_app.main()
        self.assertIn("pip install streamlit", stderr.getvalue())

    def test_jsonable_stringifies_non_json_values(self) -> None:
        self.assertEqual(streamlit_app._jsonable({"path": Path("a/b")}), {"path": "a/b"})


if __name__ == "__main__":
    unittest.main()
