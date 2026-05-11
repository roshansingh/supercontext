from __future__ import annotations

import unittest
from pathlib import Path


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
)


class ValidationReportOssPurityTest(unittest.TestCase):
    def test_source_tree_does_not_contain_private_fixture_tokens(self) -> None:
        source_root = Path(__file__).resolve().parents[2] / "source"
        hits = []
        for path in sorted(source_root.rglob("*")):
            if path.is_dir() or path.suffix in {".pyc", ".pyo"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for token in PRIVATE_TOKENS:
                if token.lower() in text:
                    hits.append(f"{path}:{token}")

        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
