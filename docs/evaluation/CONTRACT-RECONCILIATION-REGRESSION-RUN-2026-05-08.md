# Contract Reconciliation Regression Run - 2026-05-08

Status: implementation evaluation

## Scope

This run verifies the generic contract reconciliation module and checks that existing low/medium query surfaces did not regress.

Important limitation: not every low/medium row in `PRODUCT-QUERY-SET.md` is mechanically runnable yet. PR, catalog, schema, candidate/promotion, PII, alias, and SaaS/tenant fixtures remain fixture-blocked. This run covers all currently implemented low/medium CLI surfaces and all implemented LatticeAI goldset scenario plans.

## Implementation Under Test

| Component | Result |
|---|---|
| `source/kg/product/contract_reconciliation.py` | Generic scoped fact-set reconciliation by identity key. |
| `source/kg/product/scenario_plans.py` | Q100 now uses generic docs-vs-backend and clients-vs-docs reconciliation. |
| `source/kg/product/evidence_packet.py` | Reconciliation sections are normalized into evidence packet rows. |
| `source/scripts/query_kg.py` | Added `reconcile-contract` CLI. |
| `source/README.md` | Documents product-validation and reconciliation flow. |

## Verification

| Area | Command / Surface | Result |
|---|---|---|
| Compile | `python -m compileall -q source` | Pass. |
| Whitespace | `git diff --check` | Pass. |
| Low Q001 | `modules-importing pandas` | Pass: required Mercury golden citations still present. |
| Low Q002 | `modules-importing openai` | Pass: direct third-party OpenAI imports only in first results. |
| Low Q003/Q020 | `find-callers load_model` | Pass: returns ambiguity with both exact candidates. |
| Low Q004 | `find-callees predict_on_session --path ... --line 77` | Pass: returns 9 direct callees with citations. |
| Low Q005 | `symbols-in-file batch_predict.py` | Pass: returns 12 symbols including `predict_on_session`. |
| Low Q007 | `evidence-for-call predict_on_session build_features --path ... --line 77` | Pass: returns exact call evidence at line 77. |
| Low Q008/Q009/Q012 | `dependency-info os`, `top-dependencies`, `modules-importing sklearn` | Pass: `os` is stdlib; top deps exclude stdlib; `sklearn` maps to `scikit-learn`. |
| Low Q010 | `lookup-symbol FeatureBuilder` | Pass: exact candidate with path/line evidence. |
| Low Q013 | `find-callers write_result_on_disk` | Pass: direct caller is `predict_on_session` at `batch_predict.py:88`. |
| Medium Q017 | `who-imports` on Mercury and True Loop internal modules | Pass: grouped reverse importers still resolve. |
| Medium Q023 | `modules-importing-both` on both snapshots | Pass: Mercury returns 13 modules; True Loop returns 7 modules. |
| Medium Q025 | `top-internal-dependencies` on both snapshots | Pass: returns ranked internal module fan-in. |
| Medium Q026 | `dependency-path predict_on_session sklearn --path ... --line 77` | Pass: returns mixed call/import paths. |
| Medium Q030 | `top-fan-in-symbols` on both snapshots | Pass: returns ranked internal symbol fan-in. |
| True Loop low surfaces | `lookup-symbol`, `symbols-in-file`, `evidence-for-call`, `who-imports` | Pass: TS/JS parser-backed surfaces still resolve. |

## Goldset Results

Command:

```bash
python -m source.scripts.run_goldset_scenario --snapshot data/kg_runs/latticeai_23 --out docs/evaluation/LATTICEAI-GOLDSET-EVIDENCE-PACKETS-2026-05-08.json
```

| Scenario | Evidence Items | Unknowns | Result |
|---|---:|---:|---|
| Q082 | 31 | 0 | Pass for packet generation. |
| Q083 | 23 | 0 | Pass for packet generation. |
| Q088 | 8 | 0 | Pass for packet generation. |
| Q095 | 31 | 0 | Pass for packet generation. |
| Q100 | 28 | 0 | Pass for packet generation and contract reconciliation. |
| Q106 | 6 | 0 | Pass for packet generation. |

Q100 reconciliation details:

| Check | Result |
|---|---|
| Docs vs backend | 8 documented `/v1/` endpoints, 12 backend `/v1/` endpoints, 6 exact matches. |
| Documented-only | `/v1/store_data`. |
| Backend-only | `/v1/chatbot`, `/v1/elementor`, `/v1/sendgrid`, `/v1/sendgrid/<domain>`, `/v1/stripe`. |
| Possible rename | `/v1/collections` -> `/v1/product_collections` with similarity `0.789`. |
| Scope guard | Evidence comes only from `shopagain_api_docs`, `mercury_api`, and `mercury_webhooks`; no unrelated repos. |
| Packet quality | `fact_type` is populated for all Q100 rows; no null fact types. |

## Regression Verdict

No regression found in the currently implemented low/medium query surfaces. The Q100 gap moved from "needs endpoint reconciliation/diff query" to pass for deterministic packet generation.

The remaining product-value gap is not more KG extraction for Q100. It is source-byte Mode A verification plus answer synthesis over evidence packets.
