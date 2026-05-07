# Low Query Rerun: Import Normalization v1

Status: evaluation rerun  
Date: 2026-05-06  
Snapshot: `data/kg_runs/mercury_ml`  
Repo: `/Users/maruti/work/mercury_ml`  
Commit: `c83cacf1df7fa37cc5dfc51916e02b8d8933eccc`  
Extractor: `python_ast_v0` with deterministic import normalization

## Summary

| Result | Before | After |
|---|---:|---:|
| Pass | 4 | 8 |
| Partial | 7 | 6 |
| Fail | 3 | 0 |
| Blocked / not testable | 1 | 1 |

Import normalization fixed the low-tier failures without adding LLM or agentic behavior. The remaining gaps are symbol disambiguation, first-class evidence/symbol query commands, human-readable service URNs, and a candidate fixture.

## Snapshot Counts

| Metric | Before | After | Why changed |
|---|---:|---:|---|
| Python files | 225 | 225 | No corpus change. |
| Entities | 1443 | 1266 | Internal imports now point to `CodeModule` targets instead of creating many `ExternalPackage` nodes. |
| Facts | 3604 | 3653 | Import qualifiers now preserve raw import shape, category, imported names, and aliases. |
| Evidence rows | 6453 | 6567 | Normalized import facts/entities have deterministic evidence rows. |
| Coverage rows | 2 | 2 | No coverage behavior changed. |

## Results

| ID | Status | Rerun observation | Finding |
|---|---|---|---|
| Q001 | Pass | `pandas` still returns required goldens: `examples/clv/example-1.py:2`, `examples/clv/example-2.py:8`, `data_preparation.py:4`. | No regression. |
| Q002 | Pass | `openai` query now returns only normalized third-party `openai` imports. Internal wrapper imports like `mercury_ml.chatbot.apis.openai_instructor` no longer match the direct `openai` dependency query. | Direct-vs-internal package classification works. |
| Q003 | Partial | Facts still exist for both `load_model` targets and callers. | Still needs symbol ambiguity response. |
| Q004 | Partial | Expected `batch_predict.predict_on_session` callees still exist, but another same-name symbol can still be merged by loose lookup. | Still needs exact symbol resolution. |
| Q005 | Partial | Symbols in `batch_predict.py` still exist. | Still needs first-class `symbols-in-file` query. |
| Q006 | Pass | Parse coverage still reports `feature_builder_test.py` as `uninstrumented`. | No regression. |
| Q007 | Partial | Evidence for `predict_on_session -> build_features` remains at `batch_predict.py:77` with commit-pinned bytes. | Still needs user-facing evidence/Mode A command. |
| Q008 | Pass | `dependency-info os` returns category `stdlib`. | Stdlib classification works. |
| Q009 | Pass | `top-dependencies` excludes stdlib by default. Top results include `scikit-learn`, `pandas`, `llama-index`, `openai`, and `numpy`; stdlib names such as `os`, `logging`, `json`, and `pickle` are absent. | Third-party dependency ranking is now useful. |
| Q010 | Partial | `FeatureBuilder` candidates still exist with file/line evidence. | Still needs dedicated symbol lookup command and ambiguity metadata. |
| Q011 | Partial | Repo/service entities still exist, but service URN remains opaque hash-based. | Human-readable identity is separate from import normalization. |
| Q012 | Pass | `sklearn` imports now normalize to distribution `scikit-learn`, including `train.py:2` and `session_train_test_split.py:5`. | Alias mapping works for the required case. |
| Q013 | Pass | Direct caller of `write_result_on_disk` remains `batch_predict.predict_intent.predict_on_session` at `batch_predict.py:88`. | No regression. |
| Q014 | Blocked / not testable | Snapshot still has no candidate facts. | Needs candidate/enrichment fixture. |
| Q015 | Pass | Compact summary now reports 225 Python files, 1266 entities, 3653 facts, 6567 evidence rows, 2 coverage rows. | Counts changed due accepted normalization behavior. |

## Next Build Recommendation

| Priority | Build slice | Why |
|---|---|---|
| 1 | Symbol lookup and disambiguation | This is now the biggest low-tier gap: Q003, Q004, and Q010. |
| 2 | First-class evidence and symbol query commands | Converts existing data into user-facing commands for Q005 and Q007. |
| 3 | Human-readable service/repo identity | Improves Q011 but is less blocking for code-impact queries. |
| 4 | Candidate fixture | Unblocks Q014 and candidate/canonical guardrail tests. |

## Decision

Import normalization v1 is validated enough for the current KG harness. The next implementation slice should be symbol lookup/disambiguation, not more dependency normalization.
