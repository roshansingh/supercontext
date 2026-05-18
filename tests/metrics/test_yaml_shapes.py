from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from source.kg.extraction.framework.allowlists import SUPPORTED_ENTITY_KINDS, SUPPORTED_FACT_PREDICATES
from source.kg.languages._shared.dimension_rules_loader import load_dimension_rules
from source.kg.metrics.config import KNOWN_METRICS, load_metrics_config
from source.kg.metrics.compute import _parse_useful_edge_spec


class MetricsYamlShapeTest(unittest.TestCase):
    def test_default_metrics_config_enables_known_metrics(self) -> None:
        config = load_metrics_config()

        self.assertEqual(set(config.enabled_metrics), set(KNOWN_METRICS))

    def test_dimension_rules_load_strictly(self) -> None:
        root = Path("source/kg/languages")

        self.assertTrue(load_dimension_rules(root / "python" / "dimension_rules.yaml")["rules"])
        self.assertTrue(load_dimension_rules(root / "typescript" / "dimension_rules.yaml")["rules"])

    def test_dimension_rules_reject_boolean_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rules = Path(tmpdir) / "dimension_rules.yaml"
            rules.write_text(
                "version: true\n"
                "rules:\n"
                "  - id: backend\n"
                "    dimension: backend\n"
                "    imports:\n"
                "      - fastapi\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "version"):
                load_dimension_rules(rules)

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
                object_kinds = entry.get("object_kinds")
                self.assertIn(predicate, SUPPORTED_FACT_PREDICATES)
                self.assertTrue(subject_kinds or object_kinds)
                for field in ("subject_kinds", "object_kinds"):
                    if field not in entry:
                        continue
                    field_value = entry[field]
                    self.assertIsInstance(field_value, list)
                    self.assertTrue(field_value)
                    for entity_kind in field_value:
                        self.assertIsInstance(entity_kind, str)
                        self.assertTrue(entity_kind)
                        self.assertIn(entity_kind, SUPPORTED_ENTITY_KINDS)
        for row in data["adr_followups"]:
            self.assertTrue(row["adr_followup_required"])
            self.assertNotIn(row["predicate"], SUPPORTED_FACT_PREDICATES)

    def test_useful_edge_parser_rejects_unknown_entity_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported entity kind"):
            _parse_useful_edge_spec(
                Path("useful_edges.yaml"),
                {"predicate": "IMPLEMENTS", "object_kinds": ["TypoService"]},
            )

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

    def test_freshness_default_days_rejects_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "metrics.yaml"
            config.write_text(
                "enabled_metrics:\n"
                "  - M_freshness\n"
                "freshness:\n"
                "  default_days: true\n"
                "trust_weights: {}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "freshness.default_days"):
                load_metrics_config(config)


if __name__ == "__main__":
    unittest.main()
