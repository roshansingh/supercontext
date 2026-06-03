"""Deterministic, structural relevance/strength scoring for head-start budgeting.

This is the modular priority unit behind output budgeting. It answers one question:
given a set of evidence rows and a character budget, which rows are kept in full and
which are demoted to coordinate-bearing inspection references?

The score is a lexicographic tuple of structural signals the KG already produces — never
a fuzzy/semantic/learned score, never keyword overlap with a natural-language query, and
never a tuned weighted scalar. Ordering by explicit tiers keeps the cut deterministic,
reproducible across eval runs, and explainable ("kept: exact-match + known_linked").

Signal tiers (higher = kept first):

- match: how exactly the row matches the query anchor (exact id > path > substring > none).
- linkage: known_linked > candidate > unlinked > missing.
- derivation: ADR-0006 trust tier (authoritative_declared > … > inferred_llm).
- distance: nearer the anchor in the graph (smaller traversal depth) ranks higher.
- coordinates: rows carrying source coordinates outrank rows that do not.

For fleet/no-anchor queries the match tier is neutral for every row, so ordering falls
back to linkage + derivation strength.
"""

from __future__ import annotations

from typing import Optional

from source.kg.core.models import JsonObject

# ADR-0006 derivation classes, strongest first.
_DERIVATION_TIER: dict[str, int] = {
    "authoritative_declared": 5,
    "authoritative_static": 4,
    "deterministic_static": 3,
    "runtime_observed": 2,
    "inferred_llm": 1,
}
_LINKAGE_TIER: dict[str, int] = {
    "known_linked": 3,
    "candidate": 2,
    "candidate_or_unlinked": 2,
    "unlinked": 1,
    "unlinked_lead": 1,
    "inventory_context": 1,
    "missing": 0,
    "missing_or_unknown": 0,
}

ScoreKey = tuple[int, int, int, int, int]


def derivation_rank(row: JsonObject) -> int:
    """Strongest derivation tier across a row's own field or nested evidence."""
    best = _DERIVATION_TIER.get(str(row.get("derivation_class") or ""), 0)
    evidence = row.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                best = max(best, _DERIVATION_TIER.get(str(item.get("derivation_class") or ""), 0))
    return best


def linkage_rank(row: JsonObject, *, linkage: Optional[str] = None) -> int:
    """Linkage strength. An explicit caller-supplied bucket wins; else read the row."""
    if linkage is not None:
        return _LINKAGE_TIER.get(linkage, 0)
    status = row.get("status") or row.get("repo_relation") or row.get("linkage")
    return _LINKAGE_TIER.get(str(status or ""), 0)


def has_coordinates(row: JsonObject) -> bool:
    """Whether the row carries source coordinates that survive demotion to a ref."""
    if row.get("path") or row.get("bytes_ref"):
        return True
    for key in ("evidence", "source_coordinates"):
        value = row.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and (item.get("bytes_ref") or item.get("path")):
                    return True
    return False


def distance_rank(row: JsonObject) -> int:
    """Nearer the anchor ranks higher; rows without a depth are neutral (0)."""
    depth = row.get("depth")
    if isinstance(depth, bool) or not isinstance(depth, int):
        return 0
    return -depth


def match_rank(row: JsonObject, *, anchor: Optional[str] = None) -> int:
    """How exactly the row matches the anchor: exact id (3) > path (2) > substring (1)."""
    if not anchor:
        return 0
    needle = anchor.strip().lower()
    if not needle:
        return 0
    # Only string identifier fields participate; some rows carry nested dicts under keys
    # like "endpoint", and str(dict) could spuriously substring-match the anchor.
    identifiers = [
        value.lower()
        for key in ("qualified_name", "qualname", "display_name", "name", "slug", "channel", "endpoint")
        for value in [row.get(key)]
        if isinstance(value, str) and value
    ]
    if any(value == needle for value in identifiers):
        return 3
    path = row.get("path")
    path = path.lower() if isinstance(path, str) else ""
    if path and (path == needle or path.endswith(needle) or needle.endswith(path)):
        return 2
    if any(needle in value or value in needle for value in identifiers):
        return 1
    return 0


def score_key(row: JsonObject, *, anchor: Optional[str] = None, linkage: Optional[str] = None) -> ScoreKey:
    """Lexicographic priority key; higher sorts first."""
    return (
        match_rank(row, anchor=anchor),
        linkage_rank(row, linkage=linkage),
        derivation_rank(row),
        distance_rank(row),
        int(has_coordinates(row)),
    )


def rank_rows(
    rows: list[JsonObject], *, anchor: Optional[str] = None, linkage: Optional[str] = None
) -> list[JsonObject]:
    """Stable best-first ordering by structural score (ties keep input order)."""
    indexed = list(enumerate(row for row in rows if isinstance(row, dict)))
    indexed.sort(key=lambda pair: (score_key(pair[1], anchor=anchor, linkage=linkage), -pair[0]), reverse=True)
    return [row for _, row in indexed]

