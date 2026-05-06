# KG Query Smoke Tests

Input repo: `/Users/maruti/work/mercury_ml`  
Snapshot: `data/kg_runs/mercury_ml`  
Commit: `c83cacf1df7fa37cc5dfc51916e02b8d8933eccc`

| Query | Output observed | Comments |
|---|---|---|
| `summary` | 225 Python files, 1443 entities, 3604 facts, 6453 evidence rows, 2 coverage rows | Good first inventory. One syntax-error file correctly marked `uninstrumented`. |
| `modules-importing openai --limit 10` | Returned OpenAI imports in chatbot specialist agents and internal `openai_instructor` imports | Useful, but needs internal-vs-external import classification. |
| `modules-importing sklearn --limit 10` | Returned sklearn usage in training, imputers, feature builder, calibration, split modules | Good dependency evidence with file/line citations. |
| `find-callers load_model --limit 10` | Found constructors calling `load_model` in handover and frustration predictor classes | Good local call graph signal. |
| `blast-radius predict_on_session --depth 1 --limit 10` | Returned outgoing calls from `predict_on_session`: data load, impute, build features, prediction, write result | Useful, but this is outgoing call expansion, not full reverse impact/blast radius yet. |
| Aggregate JSONL inspection | Top imports: `os`, `pandas`, `logging`, `numpy`, `openai`; top callees dominated by external packages | Shows KG is grounded, but query layer needs package normalization and noise control. |

## Takeaway

The v0 KG is useful for evidence-backed code questions. Next improvements should focus on exact symbol lookup, import normalization, reverse dependency queries, and compact human-readable output.
