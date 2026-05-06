# Low Query Run: Mercury ML v0 KG

Status: evaluation run  
Date: 2026-05-06  
Snapshot: `data/kg_runs/mercury_ml`  
Repo: `/Users/maruti/work/mercury_ml`  
Commit: `c83cacf1df7fa37cc5dfc51916e02b8d8933eccc`  
Extractor: `python_ast_v0`

## Summary

| Result | Count |
|---|---:|
| Pass | 4 |
| Partial | 7 |
| Fail | 3 |
| Blocked / not testable | 1 |

Main finding: v0 extraction is good enough to start evidence-driven work, but the query layer is still too raw. The next feature should be deterministic import normalization, followed by symbol lookup/disambiguation and first-class evidence/symbol query commands.

## Results

| ID | Status | What we observed | Finding |
|---|---|---|---|
| Q001 | Pass | Found 59 `pandas` import facts. Required goldens are present: `examples/clv/example-1.py:2`, `examples/clv/example-2.py:8`, `mercury_ml/chatbot/frustration_classification/data_preparation.py:4`. | Basic import extraction with citations works. |
| Q002 | Fail | Found direct `openai` imports, but also returned internal/wrapper imports such as `mercury_ml.chatbot.apis.openai_instructor` and provider-specific modules like `llama_index.embeddings.openai`. | Needs import normalization and direct-vs-internal package classification. |
| Q003 | Partial | Found both `load_model` targets and callers: `HumanHandoverAgentDspy.load_model` called at `handover_dspy_agent.py:33`, and `FrustrationPredictor.load_model` called at `prediction.py:26`. | Correct facts exist, but the query silently merges ambiguous symbols instead of returning an ambiguity response. |
| Q004 | Partial | Found expected `batch_predict.predict_on_session` callees at lines 71, 72, 74, 76, 77, 82, 84, 86, 88. Also included another `predict_on_session` from `predict.py`. | Direct calls exist, but exact symbol resolution/disambiguation is missing. |
| Q005 | Partial | KG contains symbols defined in `batch_predict.py`, including `predict_intent.predict_on_session` at line 70 and related methods. | Data exists, but there is no first-class `symbols-in-file` query command yet. |
| Q006 | Pass | Coverage contains `PARSES` / `uninstrumented` for `mercury_ml/tests/intent_based_predictions/feature_builder_test.py`. | Parse coverage gap tracking works at v0 level. |
| Q007 | Partial | Evidence exists for `predict_on_session -> build_features` at `mercury_ml/intent_based_predictions/batch_predict.py:77` with the expected commit SHA and `deterministic_static` derivation. | Evidence row exists, but no user-facing evidence query or Mode A byte-fetch command yet. |
| Q008 | Fail | `os` appears as an import target and has 123 substring matches; it is not classified as `stdlib`. | Needs stdlib/third-party/internal import classification. |
| Q009 | Fail | Top imports include stdlib packages: `os` 97, `logging` 46, `json` 32, `pickle` 30, `datetime` 23. | Dependency ranking is not useful until stdlib/internal packages are filtered or typed. |
| Q010 | Partial | Found `FeatureBuilder` candidates with citations, including class at `feature_builder.py:13` and `build_features` at line 82. | Candidate data exists, but no dedicated symbol lookup command or ambiguity metadata. |
| Q011 | Partial | Repo and service entities exist: repo `mercury_ml`, service slug `la-mercury-ml`. URNs are opaque hashes like `supercontext://service/24f4...`. | Core entities exist, but package name and human-readable URN contract are not implemented. |
| Q012 | Partial | Found 63 `sklearn` imports, including required `train.py:2` and `session_train_test_split.py:5`. | Import facts exist, but no alias mapping from `sklearn` to distribution `scikit-learn`. |
| Q013 | Pass | Direct caller of `write_result_on_disk` is `batch_predict.predict_intent.predict_on_session` at `batch_predict.py:88`. | Reverse call lookup works for an unambiguous symbol. |
| Q014 | Blocked / not testable | Snapshot has 1443 canonical entities and 3604 canonical facts; no candidate facts exist. | Need a candidate/enrichment fixture before testing candidate-hidden behavior. |
| Q015 | Pass | Manifest matches expected counts: 225 Python files, 1443 entities, 3604 facts, 6453 evidence rows, 2 coverage rows. | KG inventory summary is reproducible. |

## Recommended Next Build

| Priority | Build slice | Why |
|---|---|---|
| 1 | Deterministic import normalization | Fixes Q002, Q008, Q009, Q012. Add package type: `stdlib`, `third_party`, `internal`, `local_unknown`; add aliases like `sklearn -> scikit-learn`; avoid substring matches for direct package queries. |
| 2 | Symbol lookup and disambiguation | Fixes Q003, Q004, Q010. Return candidate symbols with fully qualified name, kind, path, line, and require exact target selection before caller/callee traversal when ambiguous. |
| 3 | First-class evidence and symbol query commands | Fixes Q005, Q007. Add commands for `symbols-in-file`, `find-symbols`, and `evidence-for-fact`; include commit-pinned coordinate output. |
| 4 | Human-readable service/repo identity | Improves Q011. Keep existing stable IDs internally, but render ontology-aligned service/repo identity and human-readable URNs at the query surface. |
| 5 | Candidate fixture | Unblocks Q014. Add one synthetic or fixture-derived `inferred_llm` candidate fact and verify default tools hide it. |

## Decision

Do not add more extraction breadth yet. The current failure pattern says the next useful implementation work is the query contract layer over existing facts, starting with import normalization.
