# Canonical Product Validation Report

Generated: 2026-05-12T17:52:42Z

Overall status: **partial**
Quality status: **partial**
Coverage status: **partial**

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
| `product_query_set` | `docs/evaluation/PRODUCT-QUERY-SET.md` |

## Snapshot Inventory

| Corpus | Snapshot | Entities | Facts | Evidence | Coverage |
|---|---|---:|---:|---:|---:|
| Mercury ML | `data/kg_runs/mercury_ml_eval_2026_05_11` | 6613 | 24836 | 103651 | 6 |
| True Loop | `data/kg_runs/true_loop_eval_2026_05_11` | 1810 | 3659 | 7702 | 13 |
| Private Goldset | `data/kg_runs/private_goldset_eval_2026_05_11` | 17000 | 45745 | 91987 | 610 |

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
| Q083 | Medium | Private Goldset | `endpoints` | pass | endpoint_fact_count=4, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | event_fact_count=2, expected >= 1 |
| Q088 | Goldset | Private Goldset | `event-channels` | pass | source_refs: 3 rows |

## Private Goldset

Answer scores: Partial=1, Pass=8.

Evidence completeness: complete=7, partial=2.

Artifact consistency: current=9.

Goldset plan coverage: 9 judged / 14 planned.

| Scenario | Artifact | Evidence | Judged Answer | Failure Owner | Notes |
|---|---|---|---|---|---|
| Q081 | current | partial | Pass | none | The generated answer accurately reconstructs the ShopAgain runtime topology, citing api.shopagain.io→mercury_api via Apache/WSGI, app.shopagain.io for mercury_ui from Terraform, mercury_webhooks Zappa domain, mercury_tracking shopagainmail.net, campaign-message SQS producer/consumer pair, websocket route, and mercury_ml_api→mercury_ml dependency. It properly flags missing deploy evidence for prod_ml_api as required by the expected shape. |
| Q082 | current | complete | Pass | none | Evidence packet contains the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py and ServerName api.shopagain.io, the three backend service prod.ini references, and both client env-var entrypoints (REACT_APP_API_ROOT in mercury_ui/src/services/api.js:10 and VITE_API_ROOT in ShopAgainMobile/src/api/axiosConfig.tsx:8). The generated answer correctly identifies mercury_api as the backend with the WSGI entrypoint and enumerates the env-driven clients plus sibling services, matching the ground truth. |
| Q083 | current | complete | Pass | none | The EvidencePacket contains all facts in the Ground Truth: companies/urls.py lines 60-64 for auth/token routes, mercury_ui/src/services/auth.js auth callers, and ShopAgainMobile login.api.tsx:6 and axiosConfig.tsx:37 mobile callers. The generated answer correctly identifies the backend JWT token routes, the affected mobile callers with precise file/line citations, and provides the adjacent /auth/* surface (web callers in mercury_ui/src/services/auth.js) for completeness. |
| Q084 | current | complete | Pass | none | The EvidencePacket contains all key ground-truth facts: UI cancel subscription service at src/services/billing.tsx:20, PlansAndBenifits screen, mercury_api billing/urls.py Stripe routes (52-79 range), billing/views/stripe.py handlers, mercury_webhooks /v1/stripe route, views/Stripe.py with producer edge to la-prod-stripe queue from prod.ini:10, and backend consumer (process_stripe_queue.Command and stripe_event_processor). The generated answer covers all these elements with accurate citations and adds a sensible validation checklist. |
| Q088 | current | complete | Pass | none | The EvidencePacket contains all key facts required by the ground truth: CAMPAIGN_SQS producer/consumer, CAMPAIGN_MESSAGE_SQS producer and Zappa-bound consumer, and la-prod-email producer with config reference. The generated answer faithfully cites these and adds a downstream email-activity hop without distorting the core lineage. |
| Q092 | current | partial | Partial | missing KG fact, bad retrieval plan | The packet covers four of the five repo roles (storefront script in mercury_ui, mercury_websocket routes/handlers, mercury_api LiveChatViewset, mercury_ui operator routes, and ShopAgainMobile mobile UI), and the generated answer faithfully enumerates them. However, several ground-truth specifics are missing: the non-minified `shopagain_script.js`, the `shopagain-chat-widget` config repo, the websocket `$connect` route, the `mercury_websocket/handler.py` forwarding of connect/message/history events to `/campaigns/live_chat/`, the `campaigns/urls.py:77` registration, and the `WhatsApp/Conversations.js` operator UI path. The answer reflects these gaps as caveats/unknowns but cannot cover ground-truth details. |
| Q095 | current | complete | Pass | none | The EvidencePacket contains the Apache vhost routing api.shopagain.io to prod_shopagain_wsgi.py (target repo mercury_api), and references to api.shopagain.io across mercury_ui (REACT_APP_API_ROOT), ShopAgainMobile (VITE_API_ROOT), mercury_campaign_messages, mercury_tracking, and mercury_webhooks prod.ini files at the exact lines named in the ground truth. The generated answer covers all ground-truth elements and adds supplementary references that are also evidenced. |
| Q100 | current | complete | Pass | none | The evidence packet contains all the facts needed: documented endpoints in shopagain_api_docs (company, contacts, products, collections, carts, checkouts, orders, store_data), backend implementations in mercury_api/urls.py (with /v1/product_collections, /v1/elementor, /v1/chatbot as right_only), the matched /v1/store_data in mercury_webhooks/app.py:101, and the fuzzy /v1/collections vs /v1/product_collections drift. The answer correctly identifies /v1/collections as the documented-but-not-obviously-implemented case, notes the /v1/store_data placement drift to mercury_webhooks, and lists all documented endpoints lacking client callers, with citations. |
| Q106 | current | complete | Pass | none | The EvidencePacket contains the producer send-site (user_messaging.py:469), Zappa-bound consumer handler with the full queue ARN, and the downstream la-prod-email producer/consumer edges. The generated answer accurately reflects the producer, consumer, queue ARN, and downstream lineage with correct citations. |

Planned goldset scenarios not yet judged:
- `Q086`: Which repo depends on the packaged ML library, and what needs rebuild or retest if `mercury_ml` changes?
- `Q087`: If model feature-generation code changes in `mercury_ml`, which API service and deployment scripts must be checked before release?
- `Q093`: If websocket route `postChatMessage` changes, which clients and backend callbacks are affected?
- `Q099`: If `hipo-drf-exceptions` changes API error response shape, which services and clients should be validated?
- `Q101`: Which client API calls are missing from public API docs?

## Product Readout

- KG-first answers pass independent judgement when indexed facts exist: Q082, Q083, Q084, Q088, Q095, Q100, Q106.
- Remaining judged failures are concentrated in: bad retrieval plan=1, missing KG fact=1.
- Product-validation breadth is incomplete: 9/14 planned goldset scenarios have judgement rows; next run should cover Q086, Q087, Q093, Q099, Q101.
- Recommended next feature: Use the current judgement rows as the source of truth: if any scenario is Partial or Fail, prioritize the classified failure owners before expanding scope; if all judged scenarios pass, expand judged goldset coverage or add harder scenarios.

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
| `docs/evaluation/Q081-GOLDSET-ANSWERS-2026-05-12.md` | Superseded by this canonical report |
| `docs/evaluation/Q081-GOLDSET-JUDGEMENT-2026-05-12.md` | Superseded by this canonical report |
| `docs/evaluation/Q084-Q092-GOLDSET-ANSWERS-2026-05-12.md` | Superseded by this canonical report |
| `docs/evaluation/Q084-Q092-GOLDSET-JUDGEMENT-2026-05-12.md` | Superseded by this canonical report |
| `docs/evaluation/SYMBOL-QUERY-SURFACES-SMOKE-2026-05-08.md` | Superseded by this canonical report |
