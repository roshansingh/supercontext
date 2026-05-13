from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PRIVATE_TOKENS = (
    "shopagain",  # customer/product namespace
    "mercury_api",  # private backend repo
    "mercury_ui",  # private frontend repo
    "mercury_webhooks",  # private backend repo
    "ShopAgainMobile",  # private mobile repo
    "shopagain_api_docs",  # private docs repo
    "la-prod",  # private production queue prefix
    "prod_shopagain_wsgi",  # private deploy target
    "api.shopagain.io",  # private production domain
    "latticeai",  # private org/corpus namespace
    "LatticeAI",  # private org/corpus display name
    "015424956416",  # private AWS account id observed in historical fixtures
)

PRIVATE_PATH_TOKENS = (
    "/Users/",
    "/home/",
)

PUBLIC_FILE_ROOTS = (
    Path("source"),
    Path("adr"),
    Path(".github"),
)

PUBLIC_FILES = (
    Path("README.md"),
    Path("pyproject.toml"),
    Path("package.json"),
    Path("package-lock.json"),
    Path("requirements-dev.txt"),
)

SKIP_SUFFIXES = {".pyc", ".pyo"}


class ValidationReportOssPurityTest(unittest.TestCase):
    def test_public_surface_does_not_contain_private_fixture_tokens(self) -> None:
        hits = []
        for path in _public_surface_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            lowered = text.lower()
            for token in PRIVATE_TOKENS:
                if token.lower() in lowered:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")
            for token in PRIVATE_PATH_TOKENS:
                if token.lower() in lowered:
                    hits.append(f"{path.relative_to(ROOT)}:{token}")

        self.assertEqual(hits, [])


def _public_surface_files() -> list[Path]:
    files: list[Path] = []
    for root in PUBLIC_FILE_ROOTS:
        absolute_root = ROOT / root
        if not absolute_root.exists():
            continue
        for path in sorted(absolute_root.rglob("*")):
            if path.is_dir() or path.suffix in SKIP_SUFFIXES:
                continue
            files.append(path)
    for path in PUBLIC_FILES:
        absolute_path = ROOT / path
        if absolute_path.exists():
            files.append(absolute_path)
    return files


if __name__ == "__main__":
    unittest.main()
