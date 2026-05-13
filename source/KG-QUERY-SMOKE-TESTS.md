# KG Query Smoke Tests

Status: historical v0 smoke-test notes.

This file intentionally keeps the result shape generic. Do not add local machine paths,
private repository names, private domains, or customer-specific commit hashes here. For
current evaluation results, use the canonical validation report under `docs/evaluation/`.

| Query | Output observed | Comments |
|---|---|---|
| `summary` | Returned repository file counts, entity counts, fact counts, evidence counts, and coverage rows. | Good first inventory. Syntax-error files should be marked `uninstrumented`. |
| `modules-importing <package> --limit 10` | Returned importing modules with file/line evidence. | Useful dependency evidence; import normalization determines whether package names are precise. |
| `find-callers <symbol> --limit 10` | Returned local callers for an exact symbol. | Good local call graph signal when symbol identity is unambiguous. |
| `blast-radius <symbol> --depth 1 --limit 10` | Returned outgoing static call expansion from the selected symbol. | Useful, but outgoing expansion is not the same as full reverse impact analysis. |
| Aggregate JSONL inspection | Top imports and top callees were inspectable from the JSONL snapshot. | Shows KG is grounded, but query output must control external-package noise. |

## Takeaway

The v0 KG is useful for evidence-backed code questions. Next improvements should focus on exact symbol lookup, import normalization, reverse dependency queries, and compact human-readable output.
