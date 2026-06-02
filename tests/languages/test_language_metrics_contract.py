from __future__ import annotations

from collections.abc import Mapping
import unittest

from source.kg.languages import REGISTERED_LANGUAGES


class LanguageMetricsContractTest(unittest.TestCase):
    def test_registered_languages_expose_metric_contract_assets(self) -> None:
        for language in REGISTERED_LANGUAGES:
            with self.subTest(language=language.name):
                rules = language.dimension_rules()
                self.assertIsInstance(rules, Mapping)
                self.assertIsInstance(rules.get("rules"), list)
                self.assertTrue(rules.get("rules"), f"{language.name} must declare dimension rules")

                known_stacks = language.known_stacks()
                self.assertIsInstance(known_stacks, dict)
                self.assertTrue(known_stacks, f"{language.name} must declare known-stack coverage metadata")
                self.assertTrue(
                    set(known_stacks).intersection({language.name, *language.aliases}),
                    f"{language.name} known-stack keys must include the language name or an alias",
                )

                self.assertIsInstance(language.opportunity_detectors(), tuple)

    def test_package_languages_keep_resolver_and_manifest_hooks_together(self) -> None:
        for language in REGISTERED_LANGUAGES:
            with self.subTest(language=language.name):
                has_resolver = language.package_resolver() is not None
                has_manifest_extractor = language.consumer_manifest_extractor() is not None

                self.assertEqual(
                    has_resolver,
                    has_manifest_extractor,
                    f"{language.name} package resolver and consumer manifest hooks must be implemented together",
                )


if __name__ == "__main__":
    unittest.main()
