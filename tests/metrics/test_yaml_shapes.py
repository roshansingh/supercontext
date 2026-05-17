from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from source.kg.extraction.framework.allowlists import SUPPORTED_FACT_PREDICATES
from source.kg.languages._shared.dimension_rules_loader import load_dimension_rules
from source.kg.metrics.config import KNOWN_METRICS, load_metrics_config


class MetricsYamlShapeTest(unittest.TestCase):
    def test_default_metrics_config_enables_known_metrics(self) -> None:
        config = load_metrics_config()

        self.assertEqual(set(config.enabled_metrics), set(KNOWN_METRICS))

    def test_dimension_rules_load_strictly(self) -> None:
        root = Path("source/kg/languages")

        self.assertTrue(load_dimension_rules(root / "python" / "dimension_rules.yaml")["rules"])
        self.assertTrue(load_dimension_rules(root / "typescript" / "dimension_rules.yaml")["rules"])

    def test_useful_edges_are_supported_or_followups(self) -> None:
        path = Path("source/kg/metrics/useful_edges.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        dimensions = data["dimensions"]
        for dimension, entries in dimensions.items():
            self.assertIsInstance(dimension, str)
            self.assertIsInstance(entries, list)
            for entry in entries:
                self.assertIsInstance(entry, dict)
                predicate = entry.get("predicate")
                subject_kinds = entry.get("subject_kinds")
                self.assertIn(predicate, SUPPORTED_FACT_PREDICATES)
                self.assertIsInstance(subject_kinds, list)
                self.assertTrue(subject_kinds)
                for subject_kind in subject_kinds:
                    self.assertIsInstance(subject_kind, str)
                    self.assertTrue(subject_kind)
        for row in data["adr_followups"]:
            self.assertTrue(row["adr_followup_required"])
            self.assertNotIn(row["predicate"], SUPPORTED_FACT_PREDICATES)

    def test_tool_predicates_are_supported(self) -> None:
        path = Path("source/kg/metrics/tool_predicates.yaml")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        for config in data["tools"].values():
            for predicate in config["predicates"]:
                self.assertIn(predicate, SUPPORTED_FACT_PREDICATES)

    def test_trust_weights_reject_invalid_ratio_values(self) -> None:
        invalid_values = (True, -0.1, 1.1)
        for value in invalid_values:
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as tmpdir:
                    config = Path(tmpdir) / "metrics.yaml"
                    config.write_text(
                        "enabled_metrics:\n"
                        "  - M_trust_mix\n"
                        "trust_weights:\n"
                        f"  deterministic_static: {str(value).lower()}\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, "trust_weights.deterministic_static"):
                        load_metrics_config(config)


if __name__ == "__main__":
    unittest.main()
