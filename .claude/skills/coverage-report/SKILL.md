---
name: coverage-report
description: Use when the user asks to run, summarize, compare, or interpret BetterContext KG coverage metrics for a repo or fleet snapshot. Produces a deterministic `coverage-run.json` + `coverage-run.md` from the existing CLI and surfaces the smallest set of actionable findings (blocking contract flags, weakest cells, narrow next-PR recommendation). NOT for code-coverage tools like pytest-cov.
---

# KG Coverage Report

Produces consistent reports from KG snapshots using the metrics pipeline that landed in Debate-19. Every report runs deterministic CLIs; no hand-edited numbers.

## When to use

Triggers: "run coverage", "coverage report", "show metric snapshot", "what's covered for repo X", "how does the fleet score", "compare snapshot A and B", "what changed since last run", "metric drift", "is M_X partial because of Y".

## When NOT to use

- The user asks about test-line-coverage (pytest-cov, jacoco) — different tool, different domain.
- The user asks about the Debate-14 metric *design* (definitions, weights, schema) — answer from `docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md` directly without running the CLI.
- The user asks to *change* a metric formula or add a new metric — that's a debate, not a skill.

## Pre-flight (fail fast)

Verify the three artifacts exist before running anything:

```bash
test -f source/scripts/coverage_metrics.py     # metric CLI lives here
test -f source/scripts/coverage_report.py      # report renderer
test -f source/kg/metrics/config.yaml          # metric config
```

If any is missing, stop and tell the user: "Debate-19 metric infrastructure not installed; see `docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md`."

## Rules

- `metrics.jsonl`, `coverage-run.json`, and `coverage-run.md` are **generated artifacts**. Never hand-edit a value or a reason string.
- If `metrics.jsonl` exists and is newer than `entities.jsonl`/`facts.jsonl`/`coverage.jsonl`, skip recomputation — re-run only the report step.
- For fleet runs always pass `--expected-repos N` when N is known (otherwise `M_inventory` falls back to "what was ingested," which is tautologically 1.0).
- For incremental fleet runs (repo added to an existing fleet without re-running `build_multi_kg`), check for the `linker_stale` contract flag on `M_cross_repo_linkage`; if set, the right fix is `bettercontext-relink`, not adding more resolvers.

## Standard workflow

### Step 1 — Snapshot

Single repo:

```bash
python -m source.scripts.build_kg --repo <repo-path> --out <snapshot-dir>
```

Fleet (one-shot batch build):

```bash
python -m source.scripts.build_multi_kg --repo <r1> --repo <r2> ... --out <snapshot-dir>
```

Fleet (incremental — adding repo N+1 to existing fleet):

```bash
python -m source.scripts.build_kg --repo <new-repo> --out <fleet-dir>/<new-repo>
python -m source.scripts.relink --snapshot-dir <fleet-dir>     # refresh _fleet/cross_repo_links.jsonl
```

### Step 2 — Compute metrics

```bash
python -m source.scripts.coverage_metrics --snapshot <snapshot-dir> --expected-repos <N>
```

This writes `<snapshot-dir>/metrics.jsonl` (one record per (repo, dimension)).

For delta against a prior run:

```bash
python -m source.scripts.coverage_metrics --compare <snapshot-A> <snapshot-B>
```

### Step 3 — Render report

```bash
python -m source.scripts.coverage_report \
  --snapshot <snapshot-dir> \
  --out docs/evaluation/runs/<run-id> \
  --run-id <run-id> \
  --tenant <tenant-or-org> \
  --expected-repos <N> \
  --metric-config source/kg/metrics/config.yaml
```

Produces `docs/evaluation/runs/<run-id>/coverage-run.json` + `coverage-run.md`.

### Step 4 — Summarize (the actual judgment step)

Read `coverage-run.json` directly. Write a chat-message summary that surfaces the **smallest actionable set**:

1. Fleet score (one number)
2. **Blocking contract flags** — any cell with `linker_stale=true`, or `M_evidence_grounding < 1.0` on surfaced facts, or `M_silent_gap > 0` on safety-critical predicates
3. Lowest-scoring `(repo, dimension)` cell with the dominant `partial`/`n_a` reason quoted verbatim
4. Worst metric across the fleet (by value, not by state)
5. Recommended next PR — exactly one, derived from the decision tree below

Stay terse. Do not paginate every cell; the JSON file is authoritative.

## How to read `MetricValue.state`

| State | Meaning | Counts toward `cell_score`? |
|-------|---------|------------------------------|
| `usable` | Real measurement, value is meaningful | Yes |
| `partial` | Measured but missing inputs (e.g., one detector implemented out of three) | Yes, but flag `reason` |
| `n_a` | Cannot measure this cell at all (e.g., no anchor entities present) | No — sets `cell_score = None` |

A cell where one metric is `n_a` produces `cell_score: null`. That's correct behavior, not a bug — the cell is unscorable until the n_a cause is fixed.

## How to read contract flags

| Flag | Meaning | Action |
|------|---------|--------|
| `linker_stale` on `M_cross_repo_linkage` | `_fleet/manifest.json` predates per-repo snapshots OR `repo_commit_sha_set` mismatch | Run `bettercontext-relink --snapshot-dir <fleet>`; do NOT propose adding resolvers |
| `evidence_grounding_violation` on a fact | Surfaced fact lacks `bytes_ref` | File a fact-level fix; do NOT propose lowering metric threshold |
| `silent_gap` on a safety-critical predicate | `M_silent_gap > 0` on `blast_radius` / `deploy_blockers_for` input | Tool refuses if missing scope is relevant; do NOT mark cell unmeasurable |

## Decision tree — narrow next-PR recommendation

Apply in order; first match wins. Output one recommendation only.

1. **Any `linker_stale=true`** → "Run `bettercontext-relink --snapshot-dir <fleet>` against the fleet directory. Re-render."
2. **`M_evidence_grounding < 1.0` on surfaced facts** → "Fix per-fact citations in the offending adapter at `<adapter-path>`; not a metric problem."
3. **`M_cross_repo_linkage.state == "partial"` with reason mentioning `package_resolver`** → confirm PRs 9–10 (PyPI/npm resolvers) are merged in current branch; if not, point at them.
4. **`M_extractor_opportunity.state == "partial"` for a specific predicate × dim** → recommend the next extractor PR per `docs/graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md` registry.
5. **`M_useful_edge.state == "partial"` for a specific dim** → check `source/kg/metrics/useful_edges.yaml` for the dim's allowlist; recommend adding the missing predicate adapter.
6. **`M_dimension_classification.value < 0.8`** → unclassified LOC; recommend adding a framework signature to `source/kg/languages/<lang>/dimension_rules.yaml`.
7. **`M_identity_health.value < 0.95`** → likely an entity kind without per-kind URN support; recommend extending `urn_for_kind` in `source/kg/core/models.py`.
8. **Otherwise** → "No blocking findings. Lowest cell is `<repo>/<dim>` at `<score>`; root cause is `<reason>` (non-blocking)."

## Output shape — `coverage-run.json` (excerpt)

```json
{
  "run_id": "fleet-2026-05-18",
  "tenant": "mercury-ml",
  "fleet_score": 0.71,
  "expected_repos": 12,
  "indexed_repos": 11,
  "cells": [
    {
      "repo": "team-api",
      "dimension": "backend",
      "cell_score": 0.68,
      "contract_flags": ["linker_stale"],
      "commit_sha_set": ["abc123..."],
      "metric_values": {
        "M_cross_repo_linkage": {"value": 0.42, "state": "partial", "reason": "package_resolver() returns None for Python"},
        ...
      }
    }
  ]
}
```

The chat summary should NOT enumerate all `metric_values`. Quote 2–3 dominant `partial`/`n_a` reasons.

## Skill is over when

- A `coverage-run.md` exists at `docs/evaluation/runs/<run-id>/`, AND
- The chat-message summary names exactly one recommended next action (or "no blocking findings"), AND
- All contract flags from the report appear in the summary.

If the user asked for delta (snapshot-A vs snapshot-B), also include: which metrics moved by ≥0.05 and the direction.

## Verification (when modifying this skill or its underlying CLI)

```bash
python -m compileall -q source
python -m unittest tests.metrics.test_report tests.metrics.test_persistence tests.test_packaging_metadata
python -m unittest discover -s tests
```

## Related

- `docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md` — Debate-19 contract; 11 metrics; `CellMetrics` schema
- `docs/evaluation/COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md` — when `linker_stale` is the right diagnosis
- `source/kg/metrics/config.yaml` — metric weights, freshness windows, contract flag thresholds
- `source/kg/metrics/useful_edges.yaml` — per-dim allowlist driving `M_useful_edge`
- `source/kg/metrics/tool_predicates.yaml` — MCP tool → predicate map driving `M_meta_coverage`
