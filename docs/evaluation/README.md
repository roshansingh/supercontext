# Evaluation Reports

Current canonical report: [`CANONICAL-VALIDATION-REPORT.md`](CANONICAL-VALIDATION-REPORT.md).

Older dated run reports, goldset answer/judgement reports, contract-reconciliation runs, linking smokes, and symbol-query smokes were removed after being superseded by the canonical report. `source.scripts.run_product_validation` regenerates only the canonical report.

## Current A/B Baseline

Use the clean default-v1 A/B run below as the comparison baseline for context-tool improvement work:

- Local raw report: `data/ab_runs/eval-harness-baseline-full-2026-05-24/report/ab-report.md`
- Branch/PR base: PR #124, merged into `main` at `dcd07ee`
- Run shape: 18 paired tasks / 36 host runs, seed `119`, `--fixture-overrides docs/evaluation/default-v1-fixture-overrides.yaml`
- Result: `mcp_on=4`, `mcp_off=6`, `tie=8`, with zero MCP denials, zero MCP errors, and zero judge errors

Historical one-off A/B run artifacts have been removed from the repo. Keep only the current baseline above unless a future run is explicitly promoted to canonical.

Regenerate the canonical report with:

```bash
python -m source.scripts.run_product_validation
```
