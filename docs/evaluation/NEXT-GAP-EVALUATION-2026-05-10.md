# Next Gap Evaluation: Low, Medium, and LatticeAI Goldset

Date: 2026-05-10

## Scope

This run checks whether the current product validation signal points to more extraction work, retrieval planning work, or answer synthesis work.

Snapshots built fresh:

| Corpus | Snapshot | Repos | Entities | Facts | Evidence | Coverage | Extractor errors |
|---|---|---:|---:|---:|---:|---:|---|
| Mercury ML | `data/kg_runs/mercury_ml_eval_2026_05_10` | 1 | 6,613 | 24,836 | 103,651 | 5 | none |
| True Loop | `data/kg_runs/true_loop_eval_2026_05_10` | 1 | 1,814 | 3,648 | 7,677 | 6 | none |
| LatticeAI 23 | `data/kg_runs/latticeai_23_eval_2026_05_10` | 23 | 16,776 | 45,383 | 91,284 | 87 | none |

## Low/Medium Smoke

There is still no single mechanical harness for every low/medium row in `PRODUCT-QUERY-SET.md`, so this run covered all currently implemented low/medium CLI surfaces from the previous evaluation docs.

| Corpus | Covered surfaces | Result | Notes |
|---|---|---|---|
| Mercury ML | `modules-importing`, `dependency-info`, `top-dependencies`, `lookup-symbol`, `find-callers`, `find-callees`, `symbols-in-file`, `who-imports`, `modules-importing-both`, `top-internal-dependencies`, `dependency-path`, `top-fan-in-symbols` | Pass | Deterministic surfaces returned expected rows/counts. `load_model` correctly stayed ambiguous with two candidates. |
| True Loop | Same surfaces with TS/JS examples | Pass | Parser-backed TS/JS extraction remains healthy. `summary` reports endpoint and call-endpoint facts plus explicit deferred JS/TS endpoint coverage rows. |

Representative command outcomes:

| Query | Outcome |
|---|---|
| Mercury `modules-importing pandas --limit 3` | 3 cited import rows. |
| Mercury `find-callees predict_on_session --path ...batch_predict.py --line 77` | 5 cited direct callees. |
| Mercury `dependency-path predict_on_session sklearn --path ...batch_predict.py --line 77` | 5 mixed call/import paths. |
| True Loop `symbols-in-file src/lib/response-generator.ts` | 29 symbols, 5 returned. |
| True Loop `dependency-path generateResponseStream @prisma/client` | 5 paths. |

## LatticeAI Goldset

Generated files:

| Artifact | Path |
|---|---|
| Answers | `docs/evaluation/LATTICEAI-GOLDSET-ANSWERS-2026-05-10.md` |
| Judgement | `docs/evaluation/LATTICEAI-GOLDSET-JUDGEMENT-2026-05-10.md` |

Answer synthesis ran for `Q082`, `Q083`, `Q088`, `Q095`, `Q100`, and `Q106`. Judgement ran for the five scenarios with ground truth; `Q095` is marked non-goldset in `PRODUCT-QUERY-SET.md`, so it was answer-only.

| Scenario | Self score | Judged evidence | Judged answer | Failure owner | Readout |
|---|---|---|---|---|---|
| Q082 | Pass | complete | Pass | none | Domain/client/deploy answer is useful and cited. |
| Q083 | Pass | complete | Pass | none | Auth endpoint blast radius works across backend, web, and mobile. |
| Q088 | Partial | partial | Partial | missing KG fact, bad retrieval plan | Delivery queue consumer is found, but scheduling queue, producer, and status queue are missing. |
| Q095 | Pass | not judged | not judged | missing ground truth | Answer looks useful, but query set marks it `Goldset? No`. |
| Q100 | Pass | complete | Pass | none | API contract drift answer works after endpoint reconciliation. |
| Q106 | Partial | partial | Partial | bad retrieval plan, missing KG fact | Consumer evidence is good; producer send-site and downstream emit are missing. |

## Highest-Value Gap

The next highest-value gap is generic event producer/send-site extraction plus retrieval planning for event workflows.

Reasoning:

| Signal | Interpretation |
|---|---|
| Q082, Q083, Q100 pass under independent judgement | The KG plus evidence packet plus thin answer layer can produce useful real answers when the facts exist. |
| Q088 and Q106 fail for the same reason | The answer layer did not hallucinate; it correctly refused unsupported producer claims. The missing value is upstream evidence and retrieval planning. |
| Low/medium deterministic surfaces pass | The basic code graph and query surfaces are not the blocker for this next validation slice. |
| Q095 missing ground truth | Evaluation corpus needs cleanup, but this is not the product blocker. |

Recommended next PR:

1. Add a generic Python event producer extractor for high-confidence queue send-sites.
2. Resolve queue constants/settings into channel identities before emitting facts.
3. Extend scenario retrieval plans to pull producer, consumer, and downstream event edges for a channel.
4. Add or fix gold truth for Q095 so it can be judged mechanically.
5. Re-run only the LatticeAI goldset plus the low/medium smoke matrix to check movement and regressions.

Do not build a free-form agentic search layer yet. The current failures are not bad synthesis; they are missing or under-retrieved KG evidence.
