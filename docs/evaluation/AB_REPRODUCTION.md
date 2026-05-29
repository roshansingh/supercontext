# A/B Evaluation Reproduction

This page explains how repo owners can recreate SuperContext MCP A/B reports.

## Prerequisites

- Claude Code is installed and logged in.
- `.env` contains `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and `OPENAI_API_KEY`.
- The target repos and KG snapshot are available locally.
- Raw run artifacts stay under `data/ab_runs/<run-id>/`; do not commit them.

## Rerun From Scratch

Start the local MCP server:

```bash
.venv/bin/python -m source.scripts.mcp_server \
  --snapshot <snapshot-dir> \
  --host 127.0.0.1 \
  --port 3851
```

Run the paired A/B:

```bash
set -a; source .env; set +a
.venv/bin/python -m source.scripts.run_ab_eval \
  --query-set docs/evaluation/PRODUCT-QUERY-SET.md \
  --snapshot <snapshot-dir> \
  --fixture-overrides docs/evaluation/default-v1-fixture-overrides.yaml \
  --tasks default-v1 \
  --arms mcp_on,mcp_off \
  --out data/ab_runs/<run-id> \
  --seed <seed> \
  --mcp-url http://127.0.0.1:3851/mcp \
  --upload-to-langsmith
```

Pull traces, compute deltas, judge, and render:

```bash
.venv/bin/python -m source.scripts.pull_ab_traces \
  --project "$LANGSMITH_PROJECT" \
  --run-group-ids <comma-separated-run-group-ids> \
  --limit 100 \
  --out data/ab_runs/<run-id>/traces.jsonl

.venv/bin/python -m source.scripts.compute_ab_deltas \
  --traces data/ab_runs/<run-id>/traces.jsonl \
  --out data/ab_runs/<run-id>/deltas.jsonl

.venv/bin/python -m source.scripts.judge_ab_quality \
  --judge-model gpt-5.4-mini \
  --deltas data/ab_runs/<run-id>/deltas.jsonl \
  --out data/ab_runs/<run-id>/judged-deltas.jsonl \
  --seed <seed>

.venv/bin/python -m source.scripts.aggregate_ab_report \
  --deltas data/ab_runs/<run-id>/judged-deltas.jsonl \
  --out data/ab_runs/<run-id>/report

.venv/bin/python -m source.scripts.sanitize_ab_report \
  --judged-deltas data/ab_runs/<run-id>/judged-deltas.jsonl \
  --raw-report data/ab_runs/<run-id>/report/ab-report.json \
  --out docs/evaluation/ab-runs/<run-id> \
  --run-id <run-id> \
  --date <YYYY-MM-DD> \
  --judge-model gpt-5.4-mini \
  --seed <seed>
```

`compute_ab_deltas` is the standard fail-closed gate between trace capture and judging. Do not run the judge or aggregate reports directly from pulled traces. By default it rejects `mcp_on` SuperContext tool denials/errors and any trace with `incomplete_background_task_ids`; use `--allow-mcp-tool-failures` or `--allow-incomplete-background-tasks` only for explicit forensic analysis, not for promoted A/B reports.

## Prior-Loss Quality Floor

For iterative packet or prompt-contract work, use the quality-floor gate to reuse known-good `mcp_off` rows and recompute only `mcp_on`. It protects baseline `mcp_on` wins and ties from becoming `mcp_off` wins before a branch is treated as improved.

The baseline file must be a fully judged `judged-deltas.jsonl`: every selected row needs `judge_winner` set to `mcp_on`, `mcp_off`, or `tie`, and its `judge_model` / `judge_prompt_seed` must match this gate run. Do not point this gate at raw `deltas.jsonl`, an ungraded forensic run, an auto-verdict run without `judge_winner`, or a baseline judged with a different model/seed.
`--protected-baseline-winners` intentionally accepts only `mcp_on` and `tie`; baseline `mcp_off` rows are not protected because the gate is meant to catch regressions from acceptable rows into `mcp_off` wins.

```bash
.venv/bin/python -m source.scripts.mcp_quality_floor_gate \
  --snapshot <snapshot-dir> \
  --baseline-judged-deltas data/ab_runs/<baseline-run-id>/judged-deltas.jsonl \
  --reuse-mcp-off-from data/ab_runs/<baseline-run-id> \
  --out data/ab_runs/<gate-run-id> \
  --query-set docs/evaluation/PRODUCT-QUERY-SET.md \
  --fixture-overrides docs/evaluation/default-v1-fixture-overrides.yaml \
  --tasks <comma-separated-task-ids-or-omit-for-baseline-tasks> \
  --judge-model gpt-5.4-mini \
  --seed <seed>
```

This gate is a regression screen, not a replacement for the full 18-question A/B when a branch is close to merge.
Because the gate materializes local `record.json` rows into local traces, cost deltas may be unavailable in its generated report. Treat the report as a quality-floor screen; use the full LangSmith-backed A/B flow above for promoted cost/token/latency reporting.

## What Git Can Recreate

Git contains the harness, report generators, default-v1 task manifest, and sanitized reports.

Git does not contain private repo snapshots, raw Claude SDK messages, raw answers, judge reasoning, LangSmith URLs, or API keys.

## Current Clean Baseline

For context-tool improvement work, compare against the clean local baseline generated on `main` after the reverse-impact head-start packet work:

- Sanitized report: `docs/evaluation/ab-runs/main-full-18-post-q016-2026-05-28/ab-report.md`
- Local raw report: `data/ab_runs/main-full-18-post-q016-2026-05-28/report/ab-report.md`
- Snapshot: `data/kg_runs/q053_authz_budget_backfill_2026-05-27`
- Seed: `119`
- Fixture overrides: `docs/evaluation/default-v1-fixture-overrides.yaml`
- Judge: `gpt-5.4-mini`
- Result: `mcp_on=9`, `mcp_off=7`, `tie=2`
- Resources: MCP-on saved 202 tool calls, 127,207 total tokens, 447.14 seconds wall time, and $0.742113.
- Integrity checks: zero MCP denials, zero MCP errors, zero judge errors

Older raw and sanitized A/B reports may be deleted after a newer run is explicitly promoted to baseline. Keep the current baseline report above.

## Expected Checks

- `compute_ab_deltas` should fail closed if any `mcp_on` row has SuperContext MCP denials or tool errors.
- `compute_ab_deltas` should fail closed if any row has `incomplete_background_task_ids`; the runner records these for forensics, but promoted judged reports must exclude them unless explicitly labelled forensic.
- The final sanitized report should show `MCP Denied = 0`.
- Interpret token, cost, and latency only after checking the quality rubric.
