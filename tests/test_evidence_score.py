import unittest

from source.kg.product.evidence_score import (
    derivation_rank,
    has_coordinates,
    match_rank,
    rank_rows,
    score_key,
)


class EvidenceScoreTest(unittest.TestCase):
    def test_derivation_rank_orders_by_trust(self) -> None:
        # Exact integers are arbitrary; the ADR-0006 ordering and full class coverage matter.
        order = [
            "authoritative_declared",
            "manual_override",
            "deterministic_static",
            "runtime_observed",
            "inferred_llm",
        ]
        ranks = [derivation_rank({"derivation_class": cls}) for cls in order]
        self.assertEqual(ranks, sorted(ranks, reverse=True))
        self.assertEqual(len(set(ranks)), len(ranks))  # strictly decreasing
        # Every derivation_class the codebase emits is ranked above the unknown default (0).
        for cls in ("authoritative_static", "static_inferred", "candidate"):
            self.assertGreater(derivation_rank({"derivation_class": cls}), 0)
        self.assertEqual(derivation_rank({}), 0)
        # strongest nested evidence wins
        row = {"evidence": [{"derivation_class": "inferred_llm"}, {"derivation_class": "deterministic_static"}]}
        self.assertEqual(
            derivation_rank(row), derivation_rank({"derivation_class": "deterministic_static"})
        )

    def test_match_rank_exact_beats_path_beats_substring(self) -> None:
        self.assertEqual(match_rank({"qualified_name": "pkg.mod.fn"}, anchor="pkg.mod.fn"), 3)
        self.assertEqual(match_rank({"path": "pkg/mod.py"}, anchor="pkg/mod.py"), 2)
        self.assertEqual(match_rank({"qualified_name": "pkg.mod.fn"}, anchor="fn"), 1)
        self.assertEqual(match_rank({"qualified_name": "other"}, anchor="fn"), 0)
        # no anchor (fleet) is neutral for every row
        self.assertEqual(match_rank({"qualified_name": "pkg.mod.fn"}, anchor=None), 0)

    def test_has_coordinates(self) -> None:
        self.assertTrue(has_coordinates({"path": "a.py"}))
        self.assertTrue(has_coordinates({"evidence": [{"bytes_ref": {"path": "a.py", "line_start": 1}}]}))
        self.assertFalse(has_coordinates({"name": "x"}))

    def test_score_key_orders_by_linkage_then_derivation(self) -> None:
        known = {"derivation_class": "deterministic_static"}
        unlinked_strong = {"derivation_class": "authoritative_declared"}
        # known_linked beats a stronger-derivation unlinked row
        self.assertGreater(
            score_key(known, linkage="known_linked"),
            score_key(unlinked_strong, linkage="unlinked"),
        )

    def test_rank_rows_is_deterministic_and_stable(self) -> None:
        rows = [
            {"id": "a", "derivation_class": "inferred_llm"},
            {"id": "b", "derivation_class": "authoritative_declared"},
            {"id": "c", "derivation_class": "deterministic_static"},
        ]
        order = [row["id"] for row in rank_rows(rows)]
        self.assertEqual(order, ["b", "c", "a"])
        # stable: equal-score rows keep input order
        equal = [{"id": "x"}, {"id": "y"}, {"id": "z"}]
        self.assertEqual([r["id"] for r in rank_rows(equal)], ["x", "y", "z"])

    def test_distance_rank_bool_depth_is_neutral(self) -> None:
        from source.kg.product.evidence_score import distance_rank

        self.assertEqual(distance_rank({"depth": 1}), -1)
        self.assertEqual(distance_rank({"depth": 0}), 0)
        self.assertEqual(distance_rank({}), 0)
        # bool is not a usable depth (True == 1) and must be treated as neutral
        self.assertEqual(distance_rank({"depth": True}), 0)

    def test_linkage_rank_field_fallback(self) -> None:
        from source.kg.product.evidence_score import linkage_rank

        # explicit caller-supplied bucket wins
        self.assertEqual(linkage_rank({"status": "unlinked"}, linkage="known_linked"), 3)
        # else read the row, trying status -> repo_relation -> linkage
        self.assertEqual(linkage_rank({"status": "known_linked"}), 3)
        self.assertEqual(linkage_rank({"repo_relation": "unlinked"}), 1)
        self.assertEqual(linkage_rank({"linkage": "candidate"}), 2)
        self.assertEqual(linkage_rank({}), 0)


if __name__ == "__main__":
    unittest.main()
