from __future__ import annotations

import unittest

from source.kg.product.contract_reconciliation import _could_be_possible_match, _key_segments


class ContractReconciliationTest(unittest.TestCase):
    def test_endpoint_key_segments_ignore_numeric_version_prefixes(self) -> None:
        self.assertEqual(_key_segments("/v1/orders"), {"orders"})
        self.assertEqual(_key_segments("/v2/orders"), {"orders"})
        self.assertEqual(_key_segments("/v3/orders"), {"orders"})
        self.assertEqual(_key_segments("/v10/orders"), {"orders"})
        self.assertEqual(_key_segments("/v1beta/orders"), {"v1beta", "orders"})
        self.assertEqual(_key_segments("/V1/orders"), {"V1", "orders"})
        self.assertEqual(_key_segments("/version/orders"), {"version", "orders"})

    def test_possible_match_uses_versionless_segments_but_keeps_length_floor(self) -> None:
        self.assertTrue(_could_be_possible_match("/v3/orders", "/orders"))
        self.assertFalse(_could_be_possible_match("/a", "/very-long-endpoint"))


if __name__ == "__main__":
    unittest.main()
