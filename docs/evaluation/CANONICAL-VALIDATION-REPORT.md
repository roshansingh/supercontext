# Canonical Product Validation Report

Generated: 2026-05-10T11:29:00Z

Overall status: **partial**

This is the current canonical validation report for low/medium deterministic surfaces and the LatticeAI goldset. Older dated artifacts are preserved for audit history only.

## Inputs

| Input | Path |
|---|---|
| `mercury_snapshot` | `data/kg_runs/mercury_ml_eval_2026_05_10` |
| `true_loop_snapshot` | `data/kg_runs/true_loop_eval_2026_05_10` |
| `lattice_snapshot` | `data/kg_runs/latticeai_23_eval_2026_05_10` |
| `goldset_packets` | `data/kg_runs/latticeai_23_eval_2026_05_10/goldset_packets_eval_2026_05_10.json` |
| `goldset_answers` | `data/kg_runs/latticeai_23_eval_2026_05_10/goldset_answers_eval_2026_05_10.json` |
| `goldset_judgement` | `data/kg_runs/latticeai_23_eval_2026_05_10/goldset_judgement_eval_2026_05_10.json` |

## Snapshot Inventory

| Corpus | Snapshot | Entities | Facts | Evidence | Coverage |
|---|---|---:|---:|---:|---:|
| Mercury ML | `data/kg_runs/mercury_ml_eval_2026_05_10` | 6613 | 24836 | 103651 | 5 |
| True Loop | `data/kg_runs/true_loop_eval_2026_05_10` | 1814 | 3648 | 7677 | 6 |
| LatticeAI 23 | `data/kg_runs/latticeai_23_eval_2026_05_10` | 16776 | 45383 | 91284 | 87 |

## Low/Medium And Goldset Retrieval Smoke

Smoke-check IDs are corpus-scoped; the same product query ID can appear for multiple fixtures.

Result counts: pass=18.

| ID | Difficulty | Corpus | Surface | Result | Notes |
|---|---|---|---|---|---|
| Q001 | Low | Mercury ML | `modules-importing` | pass | pandas importers: 5 rows |
| Q003 | Low | Mercury ML | `lookup-symbol` | pass | status `ambiguous`, expected `ambiguous` |
| Q004 | Low | Mercury ML | `find-callees` | pass | callee_count=9, expected >= 5 |
| Q005 | Low | Mercury ML | `symbols-in-file` | pass | symbol_count=12, expected >= 1 |
| Q007 | Low | Mercury ML | `evidence-for-call` | pass | match_count=1, expected >= 1 |
| Q009 | Low | Mercury ML | `top-dependencies` | pass | top dependencies: 5 rows |
| Q013 | Low | Mercury ML | `find-callers` | pass | caller_count=1, expected >= 1 |
| Q017 | Medium | Mercury ML | `who-imports` | pass | status `resolved`, expected `resolved` |
| Q023 | Medium | Mercury ML | `modules-importing-both` | pass | status `resolved`, expected `resolved` |
| Q026 | Medium | Mercury ML | `dependency-path` | pass | status `resolved`, expected `resolved` |
| Q005 | Low | True Loop | `symbols-in-file` | pass | symbol_count=29, expected >= 1 |
| Q010 | Low | True Loop | `lookup-symbol` | pass | status `resolved`, expected `resolved` |
| Q026 | Medium | True Loop | `dependency-path` | pass | status `resolved`, expected `resolved` |
| Q032 | Medium | True Loop | `endpoints` | pass | endpoint_fact_count=34, expected >= 1 |
| Q082 | Medium | LatticeAI 23 | `domain-references` | pass | reference_count=47, expected >= 1 |
| Q083 | Medium | LatticeAI 23 | `endpoints` | pass | endpoint_fact_count=4, expected >= 1 |
| Q088 | Goldset | LatticeAI 23 | `event-channels` | pass | event_fact_count=1, expected >= 1 |
| Q095 | Medium | LatticeAI 23 | `deploy-mappings` | pass | mapping_count=1, expected >= 1 |

## LatticeAI Goldset

Answer scores: Partial=2, Pass=3.

Evidence completeness: complete=3, partial=2.

| Scenario | Evidence | Judged Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q082 | complete | Pass | none | The EvidencePacket contains all ground truth facts: Apache vhost mapping to mercury_api WSGI, ServerName at line 7, the prod.ini references for campaign_messages/tracking/webhooks, and both env-driven client references (REACT_APP_API_ROOT and VITE_API_ROOT). The generated answer correctly enumerates clients, distinguishes env-driven baseURLs, and identifies mercury_api as the served backend with the WSGI entrypoint. |
| Q083 | complete | Pass | none | The EvidencePacket contains all the ground truth facts: backend JWT routes at companies/urls.py lines 63-64, auth/auth/registration at lines 60-62, mercury-ui auth.js callers (lines 14, 23, 27 covering login/logout/registration), and ShopAgainMobile callers in login.api.tsx:6 and axiosConfig.tsx:37. The generated answer correctly identifies all required backend routes and frontend/mobile callers with proper file/line citations. |
| Q088 | partial | Partial | missing KG fact, bad retrieval plan | The evidence packet only contains the delivery queue (la-prod-campaign-messages) and its consumer. It lacks the campaign scheduling queue (CAMPAIGN_SQS / la-prod-campaign), its producer (campaign_event.py) and consumer (campaign_event_processor.py), and the la-prod-email delivery status sink. The answer correctly reports what evidence supports and explicitly flags the missing scheduling-side facts. |
| Q100 | complete | Pass | none | Evidence packet contains all documented v1 endpoints plus their backend matches/non-matches and client-call reconciliation results. The generated answer correctly identifies `/v1/collections` as the lone documented endpoint without an exact backend match (only a fuzzy match to `/v1/product_collections`) and reports that no documented endpoint has a confirmed client caller in the scoped clients reconciliation, with appropriate citations and caveats. |
| Q106 | partial | Partial | bad retrieval plan, missing KG fact | The packet proves the consumer edge (handler, ARN, Zappa binding) but contains no producer send-site evidence and no reference to the downstream `la-prod-email` response queue. The answer faithfully reflects the packet, correctly refusing to name a producer, but consequently misses the ground-truth producer (mercury_api user_messaging.py + settings.CAMPAIGN_MESSAGE_SQS / prod.py:44) and the consumer's downstream emit. |

Answer-only scenarios without judgement ground truth:
- `Q095`: self-score `Pass`, No judgement ground truth available in PRODUCT-QUERY-SET.

## Product Readout

- KG-first answers pass independent judgement when indexed facts exist: Q082, Q083, Q100.
- Remaining judged failures are concentrated in: bad retrieval plan=2, missing KG fact=2.
- Recommended next feature: After this canonical report path, prioritize generic config/env source citations for JS/TS env usage, Python settings constants, and ConfigParser-backed .ini values.

## Superseded Artifacts

The files below are historical run artifacts. Use this report for current product-validation status.

| Artifact | Status |
|---|---|
| `docs/evaluation/CONTRACT-RECONCILIATION-REGRESSION-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-CROSS-REPO-QUERY-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-ANSWERS-2026-05-09.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-ANSWERS-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-ANSWERS-Q100-PR16.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-EVENT-ANSWERS-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-EVENT-JUDGEMENT-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-JUDGEMENT-2026-05-09.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-JUDGEMENT-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/LATTICEAI-GOLDSET-JUDGEMENT-Q100-PR16.md` | Superseded by this canonical report |
| `docs/evaluation/LOW-QUERY-RERUN-IMPORT-NORMALIZATION-2026-05-06.md` | Superseded by this canonical report |
| `docs/evaluation/LOW-QUERY-RERUN-TRUE-LOOP-PARSER-BACKED-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/LOW-QUERY-RUN-2026-05-06.md` | Superseded by this canonical report |
| `docs/evaluation/LOW-QUERY-RUN-TRUE-LOOP-2026-05-07.md` | Superseded by this canonical report |
| `docs/evaluation/MEDIUM-QUERY-AGGREGATION-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/MEDIUM-QUERY-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/MIXED-CALL-IMPORT-PATH-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/MULTI-REPO-LINKING-SMOKE-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/NEXT-GAP-EVALUATION-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/SYMBOL-QUERY-SURFACES-SMOKE-2026-05-08.md` | Superseded by this canonical report |
