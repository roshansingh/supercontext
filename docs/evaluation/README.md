# Evaluation Reports

Current canonical report: [`CANONICAL-VALIDATION-REPORT.md`](CANONICAL-VALIDATION-REPORT.md).

Older evaluation run artifacts in this folder are historical snapshots. This includes dated run reports, goldset answer/judgement reports, contract-reconciliation runs, linking smokes, and symbol-query smokes. `source.scripts.run_product_validation` regenerates only the canonical report; older files are retained only for audit history and comparison.

Regenerate the canonical report with:

```bash
python -m source.scripts.run_product_validation
```
