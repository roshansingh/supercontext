# Review Context Repo Scope Resolution

Date: 2026-07-01

## Purpose

This note records the focused PR-review packet audit for owner-qualified repo arguments against single-repo local checkout snapshots.

The failure pattern was structural: `review_context` callers supplied an owner-qualified repo such as `owner/repo`, while the KG snapshot stored a local checkout repo identity. Because repo filters used the requested repo string directly, changed-range symbol lookup lost anchors even when the changed files and symbols existed in the snapshot.

## Change

`review_context` now emits `repo_resolution` and may resolve the requested repo to the snapshot repo identity only when all of these are true:

- the requested repo is owner-qualified
- the snapshot contains exactly one repo identity
- at least one changed file overlaps indexed snapshot paths or the snapshot `repo_path`

It fails closed for bare repo names, multi-repo snapshots, snapshots without repo identity, and no-overlap changed files.

Relevant implementation and tests:

- [source/kg/product/mcp_tools.py](../../source/kg/product/mcp_tools.py)
- [tests/test_mcp_tools.py](../../tests/test_mcp_tools.py)

## Evidence

Audit set: 35 routed PR-review cases with 338 changed files and 1,141 changed ranges.

Before, using original owner-qualified repo arguments:

```text
answerable cases: 0/35
symbol anchors: 0
changed symbols: 0
direct callers: 0
direct callees: 0
file anchors: 638
packet mode: 35/35 diff_anchor_only
returned cross-repo name leads: 0
omitted cross-repo name leads: 674
```

After this change, using the same owner-qualified repo arguments:

```text
repo_resolution: 35/35 resolved
answerable cases: 14/35
symbol anchors: 190
changed symbols: 166
direct callers: 75
direct callees: 273
file anchors: 448
returned cross-repo name leads: 0
omitted cross-repo name leads: 0
```

This converts the actual PR-review call path from file-anchor-only packets into anchored packets for the subset where the KG already has symbol support.

## Remaining Gap

After repo scope is fixed, the remaining file-only ranges are mostly languages or file types without indexed symbol rows in the current KG:

```text
.java: 249 ranges
.scss: 123 ranges
.rb: 76 ranges
.go: 73 ranges
.properties: 71 ranges
.js/.es6: 37 ranges
```

The next fallback/parser work should be chosen from this remaining distribution, not from the original zero-anchor result.
