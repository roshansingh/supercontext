---
name: coverage-report
description: Use when the user asks to run, summarize, compare, or standardize SuperContext KG coverage metrics for one repo or a fleet. Builds or uses a snapshot, runs coverage metrics, generates coverage-run.json and coverage-run.md via the repo CLI, and summarizes the highest-value KG coverage gaps without hand-editing numbers.
---

# Coverage Report

Use this skill to produce consistent coverage reports from KG snapshots.

## Rules

- Treat `metrics.jsonl`, `coverage-run.json`, and `coverage-run.md` as generated artifacts.
- Do not hand-edit metric values or report summaries.
- Prefer deterministic repo commands over ad hoc spreadsheet summaries.
- If a snapshot already has fresh `metrics.jsonl`, run only the report step.
- If metrics are missing, run `coverage_metrics` first.
- For fleet runs, record `--expected-repos` whenever the expected repo count is known.

## Standard Workflow

1. Build or locate the snapshot.

For one repo:

```bash
python -m source.scripts.build_kg --repo <repo-path> --out <snapshot-dir>
```

For a fleet:

```bash
python -m source.scripts.build_multi_kg --repo <repo-1> --repo <repo-2> --out <snapshot-dir>
```

2. Compute and persist metrics.

```bash
python -m source.scripts.coverage_metrics --snapshot <snapshot-dir> --expected-repos <N>
```

3. Generate the stable report.

```bash
python -m source.scripts.coverage_report \
  --snapshot <snapshot-dir> \
  --out docs/evaluation/runs/<run-id> \
  --run-id <run-id> \
  --tenant <tenant-or-org> \
  --expected-repos <N> \
  --metric-config source/kg/metrics/config.yaml
```

4. Summarize from `coverage-run.json` or `coverage-run.md`.

Report:

- fleet score
- lowest repo coverage
- weakest dimensions
- worst metrics
- coverage gaps from `coverage_gaps` (unsupported languages, uninstrumented stacks, stale/partial coverage)
- `partial` / `n_a` reasons and contract flags
- narrow next PR recommendation

## Verification

When changing the report code or skill:

```bash
python -m compileall -q source
python -m unittest tests.metrics.test_report tests.metrics.test_persistence tests.test_packaging_metadata
python -m unittest discover -s tests
```
