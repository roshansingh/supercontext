# Symbol Query Surfaces Smoke

Status: implementation smoke  
Date: 2026-05-08  
Snapshots: `data/kg_runs/mercury_ml`, `data/kg_runs/true_loop`  
Repos: `/Users/maruti/work/mercury_ml`, `/Users/maruti/work/true_loop`  

## Summary

This slice adds deterministic query surfaces over already-indexed KG data. It does not change extraction, normalization, or graph storage.

## Verified Low-Query Results

| ID | Command | Result |
|---|---|---|
| Q003 | `find-callers load_model --limit 5` | Pass: returns `status=ambiguous` with both `HumanHandoverAgentDspy.load_model` and `FrustrationPredictor.load_model` candidates. |
| Q004 | `find-callees predict_on_session --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --limit 10` | Pass: returns direct outgoing callees with citations, including `use_dumped_feature_builder`, `get_data`, `impute_data`, `build_features`, prediction methods, and `write_result_on_disk`. |
| Q005 | `symbols-in-file mercury_ml/intent_based_predictions/batch_predict.py --limit 5` | Pass: returns symbols from `batch_predict.py`, including `predict_intent.predict_on_session` at line 70. |
| Q007 | `evidence-for-call predict_on_session build_features --path mercury_ml/intent_based_predictions/batch_predict.py --line 77` | Pass: returns the `CALLS` fact with commit-pinned evidence at `batch_predict.py:77`. |
| Q010 | `lookup-symbol build_features --limit 5` | Pass: returns `status=ambiguous` with ranked fully-qualified candidates instead of silently picking one. |

## Additional Smoke Results

| Query surface | Smoke command | Result |
|---|---|---|
| `lookup-symbol` | `lookup-symbol generateResponseStream --limit 5` | Resolves uniquely to `src.lib.response-generator.generateResponseStream` with file/line evidence at `src/lib/response-generator.ts:314`. |
| `lookup-symbol` with coordinate | `lookup-symbol generateResponse --path src/lib/response-generator.ts --line 635` | Resolves the caller from the call-site coordinate when a user or tool has file/line context. |
| `evidence-for-call` TS/JS | `evidence-for-call generateResponse generateResponseStream --path src/lib/response-generator.ts --line 635` | Finds the `CALLS` fact and returns commit-pinned evidence at `src/lib/response-generator.ts:635`. |
| `blast-radius` TS/JS | `blast-radius generateResponseStream --depth 1 --limit 5` | Uses deterministic symbol resolution before traversing outgoing `CALLS` edges. |

## Remaining Limits

| Area | Status |
|---|---|
| Type-aware resolution | Still out of scope; lookup operates over indexed static symbols. |
| Cross-file exported-symbol linking | Still out of scope unless already represented by extracted `CALLS` facts. |
| Candidate/enrichment facts | Still blocked until candidate fixtures exist. |
