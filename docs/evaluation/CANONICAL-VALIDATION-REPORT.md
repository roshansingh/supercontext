# Canonical Product Validation Report

Generated: 2026-05-11T22:24:58Z

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
| True Loop | `data/kg_runs/true_loop_eval_2026_05_11` | 1810 | 3659 | 7702 | 13 |
| Private Goldset | `data/kg_runs/private_goldset_eval_2026_05_11` | 16576 | 45275 | 91024 | 135 |

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
| Q032 | Medium | True Loop | `endpoints` | pass | endpoint_fact_count=25, expected >= 1 |
| Q082 | Medium | Private Goldset | `domain-references` | pass | reference_count=40, expected >= 1 |
| Q082 | Medium | Private Goldset | `domain-references` | pass | REFERENCES_ENV_VAR: 2 rows |
| Q083 | Medium | Private Goldset | `endpoints` | pass | endpoint_fact_count=3, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | event_fact_count=2, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | source_refs: 3 rows |

## Private Goldset

Answer scores: Partial=1, Pass=5.

Evidence completeness: complete=5, partial=1.

Artifact consistency: current=6.

| Scenario | Artifact | Evidence | Judged Answer | Failure Owner | Notes |
|---|---|---|---|---|---|
| Q082 | current | complete | Pass | none | The evidence packet contains all ground truth facts: the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py, the configmanager prod.ini references in mercury_campaign_messages/mercury_tracking/mercury_webhooks, mercury_ui's REACT_APP_API_ROOT in src/services/api.js:10, and ShopAgainMobile's VITE_API_ROOT in src/api/axiosConfig.tsx:8. The answer accurately reports each of these with line-level citations and correctly identifies mercury_api as the backend. |
| Q083 | current | partial | Partial | missing KG fact, bad retrieval plan | Backend auth/token routes are well-covered in the evidence packet and reproduced in the answer with correct file/line citations. However, the packet contains no web caller facts (mercury_ui/src/services/auth.js) and only one mobile caller (axiosConfig.tsx:37 for /api/token/refresh/), missing ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/. The answer correctly acknowledges these gaps but cannot fully reconstruct the ground truth. |
| Q088 | current | complete | Pass | none | The EvidencePacket contains the key facts to reconstruct the ground truth: producer/consumer pairs for la-prod-campaign, la-prod-campaign-messages (with Zappa event source), and la-prod-email (delivery status). The generated answer covers all three required queues with producers, consumers, and Zappa citation, and adds an extra email-activity edge as caveated lineage. |
| Q095 | current | complete | Pass | none | Evidence packet contains the domain-to-WSGI mapping, the mercury_api backend binding, and all client/config references named in the ground truth. The generated answer covers each ground-truth element with precise citations. |
| Q100 | current | complete | Pass | none | The EvidencePacket contains the documented endpoints (openapi.yaml lines 67-88 and dist.json variants), the mercury_api routes (urls.py 50-58), the /v1/store_data implementation in mercury_webhooks/app.py:101, the possible_match for /v1/collections↔/v1/product_collections, and the right_only client_vs_docs rows. The answer reconstructs the ground-truth diff: it lists the documented public paths, flags /v1/collections→/v1/product_collections drift, calls out /v1/store_data placement in mercury_webhooks rather than mercury_api, and notes /v1/elementor and /v1/chatbot as code-only/undocumented. |
| Q106 | current | complete | Pass | none | The EvidencePacket contains the producer (user_messaging.py:469), the Zappa-bound consumer handler (process_campaign_message_delivery) with the full SQS ARN, and the downstream la-prod-email production/consumption. The generated answer correctly identifies producer, consumer, queue ARN, and edge proof matching the ground truth. |

## Product Readout

- KG-first answers pass independent judgement when indexed facts exist: Q082, Q088, Q095, Q100, Q106.
- Remaining judged failures are concentrated in: bad retrieval plan=1, missing KG fact=1.
- Recommended next feature: Close Q083 by adding generic JS/TS imported HTTP-client provenance and wrapper-call retrieval for axios instances such as shopagainAxios/api, then rerun the private goldset to verify /api/token/ and auth/* web/mobile caller coverage without repo-specific keywords.

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
| `docs/evaluation/PRIVATE-GOLDSET-ANSWERS-2026-05-11.md` | Superseded by this canonical report |
| `docs/evaluation/PRIVATE-GOLDSET-JUDGEMENT-2026-05-11.md` | Superseded by this canonical report |
| `docs/evaluation/SYMBOL-QUERY-SURFACES-SMOKE-2026-05-08.md` | Superseded by this canonical report |
