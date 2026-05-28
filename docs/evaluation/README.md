# Evaluation Reports

Current canonical report: [`CANONICAL-VALIDATION-REPORT.md`](CANONICAL-VALIDATION-REPORT.md).

Older dated run reports, goldset answer/judgement reports, contract-reconciliation runs, linking smokes, and symbol-query smokes were removed after being superseded by the canonical report. `source.scripts.run_product_validation` regenerates only the canonical report.

## Current A/B Baseline

Use the clean default-v1 A/B run below as the comparison baseline for context-tool improvement work:

- Sanitized report: [`ab-runs/main-full-18-post-q016-2026-05-28/ab-report.md`](ab-runs/main-full-18-post-q016-2026-05-28/ab-report.md)
- Local raw report: `data/ab_runs/main-full-18-post-q016-2026-05-28/report/ab-report.md`
- Branch/PR base: `main` at `32a69ac`
- Run shape: 18 paired tasks / 36 host runs, seed `119`, `--fixture-overrides docs/evaluation/default-v1-fixture-overrides.yaml`
- Snapshot: `data/kg_runs/q053_authz_budget_backfill_2026-05-27`
- Judge: `gpt-5.4-mini`
- Result: `mcp_on=9`, `mcp_off=7`, `tie=2`, with zero MCP denials, zero MCP errors, and zero judge errors
- Resource delta orientation: `off_minus_on`; this run saved 202 tool calls, 127,207 total tokens, 447.14 seconds wall time, and $0.742113 with MCP-on.

Historical one-off A/B run artifacts should be removed after a new baseline is promoted. Keep only the current baseline above unless a future run is explicitly promoted to canonical.

Regenerate the canonical report with:

```bash
python -m source.scripts.run_product_validation
```
