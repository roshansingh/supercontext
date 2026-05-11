# Canonical Product Validation Report

Generated: 2026-05-11T20:55:00Z

Overall status: **partial**

This is the current canonical validation report for low/medium deterministic surfaces and the private goldset. Older dated artifacts are preserved for audit history only.

## Inputs

| Input | Path |
|---|---|
| `mercury_snapshot` | `data/kg_runs/mercury_ml_eval_2026_05_11` |
| `true_loop_snapshot` | `data/kg_runs/true_loop_eval_2026_05_11` |
| `private_snapshot` | `data/kg_runs/private_goldset_eval_2026_05_11` |
| `goldset_packets` | `data/kg_runs/private_goldset_eval_2026_05_11/goldset_packets_eval_2026_05_11.json` |
| `goldset_answers` | `data/kg_runs/private_goldset_eval_2026_05_11/goldset_answers_eval_2026_05_11.json` |
| `goldset_judgement` | `data/kg_runs/private_goldset_eval_2026_05_11/goldset_judgement_eval_2026_05_11.json` |

## Snapshot Inventory

| Corpus | Snapshot | Entities | Facts | Evidence | Coverage |
|---|---|---:|---:|---:|---:|
| Mercury ML | `data/kg_runs/mercury_ml_eval_2026_05_11` | 6613 | 24836 | 103651 | 6 |
| True Loop | `data/kg_runs/true_loop_eval_2026_05_11` | 1811 | 3660 | 7704 | 6 |
| Private Goldset | `data/kg_runs/private_goldset_eval_2026_05_11` | 16575 | 45274 | 91022 | 103 |

## Low/Medium And Goldset Retrieval Smoke

Smoke-check IDs are corpus-scoped; the same product query ID can appear for multiple fixtures.

Result counts: pass=19.

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
| Q032 | Medium | True Loop | `endpoints` | pass | endpoint_fact_count=26, expected >= 1 |
| Q082 | Medium | Private Goldset | `domain-references` | pass | reference_count=40, expected >= 1 |
| Q082 | Medium | Private Goldset | `domain-references` | pass | REFERENCES_ENV_VAR: 2 rows |
| Q083 | Medium | Private Goldset | `endpoints` | pass | endpoint_fact_count=2, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | event_fact_count=2, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | source_refs: 3 rows |

## Private Goldset

Answer scores: Partial=1, Pass=5.

Evidence completeness: complete=4, partial=2.

Artifact consistency: current=6.

| Scenario | Artifact | Evidence | Judged Answer | Failure Owner | Notes |
|---|---|---|---|---|---|
| Q082 | current | complete | Pass | none | The evidence packet contains the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py with ServerName api.shopagain.io, the client env-var references (REACT_APP_API_ROOT in mercury_ui/src/services/api.js:10 and VITE_API_ROOT in ShopAgainMobile/src/api/axiosConfig.tsx:8), and the backend service config references in mercury_campaign_messages, mercury_tracking, and mercury_webhooks prod.ini files at the cited lines, plus docs. The generated answer faithfully synthesizes all these facts with correct citations. |
| Q083 | current | partial | Partial | bad retrieval plan, missing KG fact | The packet successfully retrieves the backend auth/token routes (including the specific `api/token/`, `api/token/refresh/`, `auth/`, and `auth/registration/` lines in companies/urls.py), but contains no evidence about web (mercury_ui) or mobile (ShopAgainMobile) callers. The generated answer correctly reports the backend routes and honestly states it cannot identify frontend/mobile callers from the supplied evidence, but this leaves the ground truth's caller files (auth.js, login.api.tsx, axiosConfig.tsx) uncovered. |
| Q088 | current | complete | Pass | none | The EvidencePacket contains all three core queues (la-prod-campaign, la-prod-campaign-messages, la-prod-email) plus the la-prod-email-activity bonus, with producers, consumers, Zappa event source, and INI config references. The generated answer accurately covers all ground truth edges with correct file:line citations. |
| Q095 | current | complete | Pass | none | The EvidencePacket contains the domain-to-WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), the backend repo (mercury_api), and all client/config references named in the ground truth. The generated answer covers each ground-truth element with correct file paths and line numbers. |
| Q100 | current | complete | Pass | none | The EvidencePacket contains the full set of documented v1 paths (openapi.yaml, dist.json) and implemented v1 paths (mercury_api/urls.py, mercury_webhooks/app.py) plus the fuzzy-match flag for /v1/collections vs /v1/product_collections. The Generated Answer correctly identifies the drift items relevant to the question: all documented endpoints lack evidenced client callers, /v1/collections only fuzzy-matches /v1/product_collections, and /v1/store_data is implemented in mercury_webhooks rather than the main mercury_api backend, with proper citations and caveats. |
| Q106 | current | partial | Pass | none | Evidence packet captures the producer send-site, the Zappa-wired consumer handler with full ARN, and the downstream la-prod-email lineage. The generated answer covers all key elements of the ground truth (producer file/lines, consumer handler, queue ARN, downstream emission to la-prod-email). |

## Product Readout

- KG-first answers pass independent judgement when indexed facts exist: Q082, Q088, Q095, Q100.
- Remaining judged failures are concentrated in: bad retrieval plan=1, missing KG fact=1.
- Recommended next feature: Add generic client-side endpoint caller extraction and retrieval for JS/TS HTTP clients, then rerun Q083 and Q100 to distinguish true no-caller cases from missing caller evidence.

## Superseded Artifacts

The files below are historical run artifacts. Use this report for current product-validation status.

| Artifact | Status |
|---|---|
| `docs/evaluation/CONTRACT-RECONCILIATION-REGRESSION-RUN-2026-05-08.md` | Superseded by this canonical report |
| `docs/evaluation/GOLDSET-ARTIFACT-CONSISTENCY-TRIAGE-2026-05-10.md` | Superseded by this canonical report |
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
| `docs/evaluation/NEXT-GAP-ANALYSIS-POST-PR17-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/NEXT-GAP-EVALUATION-2026-05-10.md` | Superseded by this canonical report |
| `docs/evaluation/SYMBOL-QUERY-SURFACES-SMOKE-2026-05-08.md` | Superseded by this canonical report |
