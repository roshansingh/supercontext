# Product Query Set Run

Generated: 2026-05-12T21:21:15Z

Product query set: `docs/evaluation/PRODUCT-QUERY-SET.md`

This report is the Debate 12 Step 1 measurement matrix. It records every product query as measured or `unmeasured` without pretending unsupported surfaces have an executable harness.

## Summary

- Unique queries: 110
- Query/corpus tuples: 117
- Measured queries: 24 / 110
- Unmeasured queries: 86 / 110
- Measured query coverage: 21.8%
- Current harness sources: deterministic smoke, fixture binding, goldset judgement

Status counts: partial=2, pass=24, unmeasured=91.

Difficulty counts: Hard=55, Low=15, Medium=40.

## Failure Owners

Failure-owner counts: missing KG fact=2, bad retrieval plan=1, bad synthesis=0, bad ground truth=0, coverage gap=91.

| Failure owner | Query/corpus tuples |
|---|---:|
| missing KG fact | 2 |
| bad retrieval plan | 1 |
| bad synthesis | 0 |
| bad ground truth | 0 |
| coverage gap | 91 |

## Matrix

| ID | Difficulty | Corpus | Status | Failure Owner | Harness | Notes |
|---|---|---|---|---|---|---|
| Q001 | Low | Mercury ML | pass | none | deterministic smoke | pandas importers: 5 rows |
| Q002 | Low | Mercury ML | pass | none | fixture binding | openai direct third-party importers: 37 rows |
| Q003 | Low | Mercury ML | pass | none | deterministic smoke | status `ambiguous`, expected `ambiguous` |
| Q004 | Low | Mercury ML | pass | none | deterministic smoke | callee_count=9, expected >= 5 |
| Q005 | Low | Mercury ML | pass | none | deterministic smoke | symbol_count=12, expected >= 1 |
| Q005 | Low | True Loop | pass | none | deterministic smoke | symbol_count=29, expected >= 1 |
| Q006 | Low | Mercury ML | pass | none | fixture binding | coverage rows for mercury_ml/tests/intent_based_predictions/feature_builder_test.py: 2 rows |
| Q007 | Low | Mercury ML | pass | none | deterministic smoke | match_count=1, expected >= 1 |
| Q008 | Low | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q009 | Low | Mercury ML | pass | none | deterministic smoke | top dependencies: 5 rows |
| Q010 | Low | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q010 | Low | True Loop | pass | none | deterministic smoke | status `resolved`, expected `resolved` |
| Q011 | Low | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q012 | Low | Mercury ML | partial | missing KG fact | fixture binding | sklearn importers: 89 rows; distribution mapping missing |
| Q013 | Low | Mercury ML | pass | none | deterministic smoke | caller_count=1, expected >= 1 |
| Q014 | Low | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q015 | Low | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q016 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q017 | Medium | Mercury ML | pass | none | deterministic smoke | status `resolved`, expected `resolved` |
| Q018 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q019 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q020 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q021 | Medium | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q022 | Medium | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q023 | Medium | Mercury ML | pass | none | deterministic smoke | status `resolved`, expected `resolved` |
| Q024 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q025 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q026 | Medium | Mercury ML | pass | none | deterministic smoke | status `resolved`, expected `resolved` |
| Q026 | Medium | True Loop | pass | none | deterministic smoke | status `resolved`, expected `resolved` |
| Q027 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q028 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q029 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q030 | Medium | Mercury ML | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q031 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q032 | Medium | True Loop | pass | none | deterministic smoke | endpoint_fact_count=25, expected >= 1 |
| Q032 | Medium | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $SERVICE has no binding for corpus Unspecified fixture. |
| Q033 | Medium | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $ENDPOINT has no binding for corpus Unspecified fixture. |
| Q034 | Medium | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q035 | Medium | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $SERVICE has no binding for corpus Unspecified fixture. |
| Q036 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q037 | Hard | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q038 | Hard | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $EVENT has no binding for corpus Unspecified fixture. |
| Q039 | Hard | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $SERVICE has no binding for corpus Unspecified fixture. |
| Q040 | Hard | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $SERVICE has no binding for corpus Unspecified fixture. |
| Q041 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q042 | Hard | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q043 | Hard | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $ENDPOINT has no binding for corpus Unspecified fixture. |
| Q044 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q045 | Hard | Unspecified fixture | unmeasured | coverage gap | none | Fixture variable $SERVICE has no binding for corpus Unspecified fixture. |
| Q046 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q047 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q048 | Hard | PR fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q049 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q050 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q051 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q052 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q053 | Hard | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q054 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q055 | Medium | Unspecified fixture | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q056 | Medium | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q057 | Medium | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q058 | Medium | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q059 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q060 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q061 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q062 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q063 | Medium | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q064 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q065 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q066 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q067 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q068 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q069 | Medium | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q070 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q071 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q072 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q073 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q074 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q075 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q076 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q077 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q078 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q078 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q079 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q079 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q080 | Hard | llm-app-stack | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q080 | Hard | otel-demo | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q081 | Hard | Private Goldset | pass | none | goldset judgement | The generated answer accurately reconstructs the ShopAgain runtime topology, citing api.shopagain.io→mercury_api via Apache/WSGI, app.shopagain.io for mercury_ui from Terraform, mercury_webhooks Zappa domain, mercury_tracking shopagainmail.net, campaign-message SQS producer/consumer pair, websocket route, and mercury_ml_api→mercury_ml dependency. It properly flags missing deploy evidence for prod_ml_api as required by the expected shape. |
| Q082 | Medium | Private Goldset | pass | none | deterministic smoke, goldset judgement | reference_count=40, expected >= 1; REFERENCES_ENV_VAR: 2 rows; Evidence packet contains the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py and ServerName api.shopagain.io, the three backend service prod.ini references, and both client env-var entrypoints (REACT_APP_API_ROOT in mercury_ui/src/services/api.js:10 and VITE_API_ROOT in ShopAgainMobile/src/api/axiosConfig.tsx:8). The generated answer correctly identifies mercury_api as the backend with the WSGI entrypoint and enumerates the env-driven clients plus sibling services, matching the ground truth. |
| Q083 | Medium | Private Goldset | pass | none | deterministic smoke, goldset judgement | endpoint_fact_count=4, expected >= 1; The EvidencePacket contains all facts in the Ground Truth: companies/urls.py lines 60-64 for auth/token routes, mercury_ui/src/services/auth.js auth callers, and ShopAgainMobile login.api.tsx:6 and axiosConfig.tsx:37 mobile callers. The generated answer correctly identifies the backend JWT token routes, the affected mobile callers with precise file/line citations, and provides the adjacent /auth/* surface (web callers in mercury_ui/src/services/auth.js) for completeness. |
| Q084 | Hard | Private Goldset | pass | none | goldset judgement | The EvidencePacket contains all key ground-truth facts: UI cancel subscription service at src/services/billing.tsx:20, PlansAndBenifits screen, mercury_api billing/urls.py Stripe routes (52-79 range), billing/views/stripe.py handlers, mercury_webhooks /v1/stripe route, views/Stripe.py with producer edge to la-prod-stripe queue from prod.ini:10, and backend consumer (process_stripe_queue.Command and stripe_event_processor). The generated answer covers all these elements with accurate citations and adds a sensible validation checklist. |
| Q085 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q086 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q087 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q088 | Hard | Private Goldset | pass | none | deterministic smoke, goldset judgement | event_fact_count=2, expected >= 1; source_refs: 3 rows; The EvidencePacket contains all key facts required by the ground truth: CAMPAIGN_SQS producer/consumer, CAMPAIGN_MESSAGE_SQS producer and Zappa-bound consumer, and la-prod-email producer with config reference. The generated answer faithfully cites these and adds a downstream email-activity hop without distorting the core lineage. |
| Q089 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q090 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q091 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q092 | Hard | Private Goldset | partial | bad retrieval plan, missing KG fact | goldset judgement | The packet covers four of the five repo roles (storefront script in mercury_ui, mercury_websocket routes/handlers, mercury_api LiveChatViewset, mercury_ui operator routes, and ShopAgainMobile mobile UI), and the generated answer faithfully enumerates them. However, several ground-truth specifics are missing: the non-minified `shopagain_script.js`, the `shopagain-chat-widget` config repo, the websocket `$connect` route, the `mercury_websocket/handler.py` forwarding of connect/message/history events to `/campaigns/live_chat/`, the `campaigns/urls.py:77` registration, and the `WhatsApp/Conversations.js` operator UI path. The answer reflects these gaps as caveats/unknowns but cannot cover ground-truth details. |
| Q093 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q094 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q095 | Medium | Private Goldset | pass | none | goldset judgement | The EvidencePacket contains the Apache vhost routing api.shopagain.io to prod_shopagain_wsgi.py (target repo mercury_api), and references to api.shopagain.io across mercury_ui (REACT_APP_API_ROOT), ShopAgainMobile (VITE_API_ROOT), mercury_campaign_messages, mercury_tracking, and mercury_webhooks prod.ini files at the exact lines named in the ground truth. The generated answer covers all ground-truth elements and adds supplementary references that are also evidenced. |
| Q096 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q097 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q098 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q099 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q100 | Hard | Private Goldset | pass | none | goldset judgement | The evidence packet contains all the facts needed: documented endpoints in shopagain_api_docs (company, contacts, products, collections, carts, checkouts, orders, store_data), backend implementations in mercury_api/urls.py (with /v1/product_collections, /v1/elementor, /v1/chatbot as right_only), the matched /v1/store_data in mercury_webhooks/app.py:101, and the fuzzy /v1/collections vs /v1/product_collections drift. The answer correctly identifies /v1/collections as the documented-but-not-obviously-implemented case, notes the /v1/store_data placement drift to mercury_webhooks, and lists all documented endpoints lacking client callers, with citations. |
| Q101 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q102 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q103 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q104 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q105 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q106 | Medium | Private Goldset | pass | none | goldset judgement | The EvidencePacket contains the producer send-site (user_messaging.py:469), Zappa-bound consumer handler with the full queue ARN, and the downstream la-prod-email producer/consumer edges. The generated answer accurately reflects the producer, consumer, queue ARN, and downstream lineage with correct citations. |
| Q107 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q108 | Medium | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q109 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
| Q110 | Hard | Private Goldset | unmeasured | coverage gap | none | No executable smoke, packet, answer, or judgement harness exists for this query/corpus tuple yet. |
