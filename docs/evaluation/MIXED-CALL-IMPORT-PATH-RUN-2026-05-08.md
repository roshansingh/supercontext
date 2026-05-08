# Mixed Call/Import Path Run

Status: implementation evaluation
Date: 2026-05-08
Snapshots: `data/kg_runs/mercury_ml`, `data/kg_runs/true_loop`
Implemented plan: deterministic dependency-path query for Q026.

## Summary

The `dependency-path` surface adds deterministic shortest-path search over existing `CALLS`, `DEFINED_IN`, and `IMPORTS` facts. It converts Q026 from fail to pass on both repos without changing extraction, normalization, storage, or low-tier behavior.

| Repo | Low pass | Low partial | Low fail | Low blocked | Medium pass | Medium partial | Medium fail | Medium blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `mercury_ml` | 13 | 1 | 0 | 1 | 6 | 5 | 3 | 10 |
| `true_loop` | 13 | 1 | 0 | 1 | 6 | 4 | 3 | 11 |

Previous medium baseline after aggregation PR:

| Repo | Pass | Partial | Fail | Blocked |
|---|---:|---:|---:|---:|
| `mercury_ml` | 5 | 5 | 4 | 10 |
| `true_loop` | 5 | 4 | 4 | 11 |

## Commands Run

| Area | Command | Result |
|---|---|---|
| Compile | `python -m compileall -q source` | Pass. |
| Whitespace check | `git diff --check -- source/kg/path_search.py source/kg/queries.py source/scripts/query_kg.py source/README.md` | Pass. |
| Mercury Q026 default ambiguity | `dependency-path predict_on_session sklearn --max-depth 4 --limit 5` | Correctly returns `status=ambiguous` because `predict_on_session` has two exact candidates. |
| Mercury Q026 with coordinate | `dependency-path predict_on_session sklearn --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --max-depth 4 --limit 5` | Pass: returns 5 paths to `scikit-learn`; shortest path is `predict_on_session -> batch_predict module -> threshold_finder -> scikit-learn`. |
| Mercury direct package path | `dependency-path predict_on_session pandas --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --max-depth 4 --limit 5` | Pass: returns 5 paths, including direct module import path to `pandas`. |
| Mercury wrapper path | `dependency-path chat_completion_request_instructor openai --path mercury_ml/chatbot/apis/openai_instructor.py --line 30 --max-depth 4 --limit 5` | Pass: returns `chat_completion_request_instructor -> openai_instructor module -> openai`. |
| Mercury include-all | `dependency-path chat_completion_request_instructor openai --include-all --max-depth 4 --limit 5` | Pass: returns paths for both exact source candidates. |
| True Loop internal module path | `dependency-path generateResponseStream src.lib.ai-client --max-depth 4 --limit 5` | Pass: returns 5 paths, including direct `CALLS` to `src.lib.ai-client` and module import paths. |
| True Loop empty path | `dependency-path generateResponseStream react --max-depth 4 --limit 5` | Pass: returns `status=empty` with resolved source/target. |
| True Loop missing target | `dependency-path generateResponseStream openai --max-depth 4 --limit 5` | Pass: returns `status=not_found` for target because the fixture has no OpenAI target. |
| Error handling | `dependency-path nonexistent_symbol pandas --max-depth 4 --limit 5` | Pass: returns `status=not_found` for source. |
| Error handling | `dependency-path predict_on_session nonexistent_target --path ... --line 77` | Pass: returns `status=not_found` for target. |
| Cap clamping | `dependency-path predict_on_session sklearn --path ... --line 77 --max-depth 99 --limit 999` | Pass: response shows `max_depth=6`, `limit=25`. |
| No-regression smoke | `find-callees predict_on_session --path ... --line 77 --limit 10` | Pass. |
| No-regression smoke | `modules-importing-both pandas sklearn --limit 5` | Pass. |
| No-regression smoke | `top-fan-in-symbols --snapshot data/kg_runs/true_loop --limit 5` | Pass. |

## Medium Query Movement

| ID | Area | Mercury | True Loop | Finding |
|---|---|---|---|---|
| Q026 | Dependency path from symbol to package/module | Pass | Pass | New `dependency-path` answers the mixed `CALLS` + `DEFINED_IN` + `IMPORTS` path query with evidence per edge. |
| Q018 | Indirect OpenAI through wrappers | Better partial | Blocked | Mercury can now prove wrapper-to-OpenAI paths; still no combined wrapper-importer query. True Loop has no OpenAI fixture. |
| Q027 | Remove dependency impact | Better partial | Better partial | Path evidence is available, but break-first ranking is still not implemented. |

## Remaining Medium Gaps

| Category | Query IDs | Reason |
|---|---|---|
| Reverse transitive impact | Q016 | Direct and dependency paths exist, but generalized reverse transitive blast-radius is not implemented. |
| External API caller ranking | Q024 | Needs aggregation over external `CALLS` facts by caller/module. |
| Inspection/test retrieval | Q019, Q028 | Needs a combined inspection-plan surface and lexical/test retrieval. |
| Coverage dashboard/refusal | Q029, Q054 | Coverage rows exist, but product-level refusal and grouped coverage surfaces are missing. |
| Fixture-blocked platform queries | Q021, Q022, Q031-Q035, Q051, Q052, Q055 | Need PR, catalog/owner, endpoint/schema, deploy, candidate/promotion, PII, and alias fixtures. |

## Decision

This is the last single-repo KG primitive we should add before product validation. Next work should move to multi-repo validation and the freshness/incremental-indexing design.
