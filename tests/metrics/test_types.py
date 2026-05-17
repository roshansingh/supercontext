from __future__ import annotations

import unittest

from source.kg.metrics.types import MetricValue


class MetricTypesTest(unittest.TestCase):
    def test_metric_value_rejects_unknown_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "MetricValue.state"):
            MetricValue(0.0, "bad")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
