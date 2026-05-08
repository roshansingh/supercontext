# Symbol Query Surfaces Smoke

Status: implementation smoke  
Date: 2026-05-08  
Snapshot: `data/kg_runs/true_loop`  
Repo: `/Users/maruti/work/true_loop`  

## Summary

This slice adds deterministic query surfaces over already-indexed KG data. It does not change extraction, normalization, or graph storage.

| Query surface | Smoke command | Result |
|---|---|---|
| `lookup-symbol` | `lookup-symbol generateResponseStream --limit 5` | Resolves uniquely to `src.lib.response-generator.generateResponseStream` with file/line evidence at `src/lib/response-generator.ts:314`. |
| `lookup-symbol` with coordinate | `lookup-symbol generateResponse --path src/lib/response-generator.ts --line 635` | Resolves the caller from the call-site coordinate when a user or tool has file/line context. |
| `symbols-in-file` | `symbols-in-file src/lib/response-generator.ts --limit 8` | Returns symbols from the file in source order with evidence-backed coordinates. |
| `evidence-for-call` | `evidence-for-call generateResponse generateResponseStream --path src/lib/response-generator.ts --line 635` | Finds the `CALLS` fact and returns commit-pinned evidence at `src/lib/response-generator.ts:635`. |
| `evidence-for-call` with ambiguous names | `evidence-for-call predict_on_session build_features --path mercury_ml/intent_based_predictions/batch_predict.py --line 77` | Uses the call-site coordinate to resolve the local caller and callee despite globally ambiguous `build_features` symbols. |

## Expected Low-Query Movement

| ID | Before | Expected after this slice | Reason |
|---|---|---|---|
| Q003 | Partial | Pass likely | Symbol resolution now returns explicit `resolved` vs `ambiguous` status instead of relying on loose substring matching. |
| Q005 | Partial | Pass likely | `symbols-in-file` exposes already-indexed symbols as a first-class query. |
| Q007 | Partial | Pass likely | `evidence-for-call` exposes coordinate-backed call evidence directly. |
| Q010 | Partial | Pass likely | `lookup-symbol` returns ranked candidates and ambiguity metadata for same-name/fuzzy cases. |

## Remaining Limits

| Area | Status |
|---|---|
| Type-aware resolution | Still out of scope; lookup operates over indexed static symbols. |
| Cross-file exported-symbol linking | Still out of scope unless already represented by extracted `CALLS` facts. |
| Candidate/enrichment facts | Still blocked until candidate fixtures exist. |
