# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/latticeai_23_eval_2026_05_10/goldset_packets_eval_2026_05_10.json`
- Answers: `data/kg_runs/latticeai_23_eval_2026_05_10/goldset_answers_eval_2026_05_10.json`
- Model: `opus`
- Scenario count: 5
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q082 | complete | Pass | none | The EvidencePacket contains all ground truth facts: Apache vhost mapping to mercury_api WSGI, ServerName at line 7, the prod.ini references for campaign_messages/tracking/webhooks, and both env-driven client references (REACT_APP_API_ROOT and VITE_API_ROOT). The generated answer correctly enumerates clients, distinguishes env-driven baseURLs, and identifies mercury_api as the served backend with the WSGI entrypoint. |
| Q083 | complete | Pass | none | The EvidencePacket contains all the ground truth facts: backend JWT routes at companies/urls.py lines 63-64, auth/auth/registration at lines 60-62, mercury-ui auth.js callers (lines 14, 23, 27 covering login/logout/registration), and ShopAgainMobile callers in login.api.tsx:6 and axiosConfig.tsx:37. The generated answer correctly identifies all required backend routes and frontend/mobile callers with proper file/line citations. |
| Q088 | partial | Partial | missing KG fact, bad retrieval plan | The evidence packet only contains the delivery queue (la-prod-campaign-messages) and its consumer. It lacks the campaign scheduling queue (CAMPAIGN_SQS / la-prod-campaign), its producer (campaign_event.py) and consumer (campaign_event_processor.py), and the la-prod-email delivery status sink. The answer correctly reports what evidence supports and explicitly flags the missing scheduling-side facts. |
| Q100 | complete | Pass | none | Evidence packet contains all documented v1 endpoints plus their backend matches/non-matches and client-call reconciliation results. The generated answer correctly identifies `/v1/collections` as the lone documented endpoint without an exact backend match (only a fuzzy match to `/v1/product_collections`) and reports that no documented endpoint has a confirmed client caller in the scoped clients reconciliation, with appropriate citations and caveats. |
| Q106 | partial | Partial | bad retrieval plan, missing KG fact | The packet proves the consumer edge (handler, ARN, Zappa binding) but contains no producer send-site evidence and no reference to the downstream `la-prod-email` response queue. The answer faithfully reflects the packet, correctly refusing to name a producer, but consequently misses the ground-truth producer (mercury_api user_messaging.py + settings.CAMPAIGN_MESSAGE_SQS / prod.py:44) and the consumer's downstream emit. |

## Q082 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all ground truth facts: Apache vhost mapping to mercury_api WSGI, ServerName at line 7, the prod.ini references for campaign_messages/tracking/webhooks, and both env-driven client references (REACT_APP_API_ROOT and VITE_API_ROOT). The generated answer correctly enumerates clients, distinguishes env-driven baseURLs, and identifies mercury_api as the served backend with the WSGI entrypoint.

### Ground Truth Coverage

- Apache vhost prod_shopagain.conf maps / to /home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py (lines 2-7) — covered
- ServerName api.shopagain.io at line 7 — covered
- mercury_campaign_messages/configmanager/prod.ini:8 — covered
- mercury_tracking/common/configmanager/prod.ini:8 — covered
- mercury_webhooks/common/configmanager/prod.ini:28 — covered
- mercury_ui REACT_APP_API_ROOT env var — covered (env.production cited; ground truth cites src/services/api.js:10 which is not in packet but the env-driven nature is captured)
- ShopAgainMobile VITE_API_ROOT env var — covered (env files cited; ground truth cites src/api/axiosConfig.tsx:8 which is not in packet but env-driven nature is captured)
- Backend = mercury_api — covered

### Missing Or Weak Evidence

- Ground truth specifically cites mercury_ui/src/services/api.js:10 and ShopAgainMobile/src/api/axiosConfig.tsx:8 as the consumer files for the env vars; the packet only shows the .env files and minified bundles, not the source consumers. This is a minor gap but the env-driven claim is still supported.

### Answer Issues

- None.

### Recommended Next Action

Optionally enrich retrieval to include source files that read REACT_APP_API_ROOT and VITE_API_ROOT (api.js, axiosConfig.tsx) for stronger client-side traceability, but the current answer is acceptable.

## Q083 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all the ground truth facts: backend JWT routes at companies/urls.py lines 63-64, auth/auth/registration at lines 60-62, mercury-ui auth.js callers (lines 14, 23, 27 covering login/logout/registration), and ShopAgainMobile callers in login.api.tsx:6 and axiosConfig.tsx:37. The generated answer correctly identifies all required backend routes and frontend/mobile callers with proper file/line citations.

### Ground Truth Coverage

- Backend auth routes auth/ and auth/registration/ at companies/urls.py:60-62 — covered
- JWT token routes api/token/ and api/token/refresh/ at companies/urls.py:63-64 — covered
- Web callers in mercury_ui/src/services/auth.js (login/logout/registration) — covered (logout L14, registration L27, plus additional auth calls)
- Mobile caller ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/ — covered
- Mobile caller ShopAgainMobile/src/api/axiosConfig.tsx:37 for /api/token/refresh/ — covered

### Missing Or Weak Evidence

- Ground truth references auth.js:5-27 as 'login/logout/registration', but the packet does not contain a specific line 5 login call; logout (L14) and registration (L27) are evidenced. This is a minor gap but does not block reconstruction since the file/range is identifiable.

### Answer Issues

- Answer states web app 'is not directly affected' by JWT token endpoint changes, which aligns with the packet but slightly under-emphasizes that mercury-ui likely has token handling not captured here; this is properly caveated.

### Recommended Next Action

Accept as Pass. Optionally, expand retrieval to capture any mercury-ui token-related calls (e.g., login flow) for completeness in future runs.

## Q088 - Partial

**Evidence completeness:** partial

**Failure owner:** missing KG fact, bad retrieval plan

### Summary

The evidence packet only contains the delivery queue (la-prod-campaign-messages) and its consumer. It lacks the campaign scheduling queue (CAMPAIGN_SQS / la-prod-campaign), its producer (campaign_event.py) and consumer (campaign_event_processor.py), and the la-prod-email delivery status sink. The answer correctly reports what evidence supports and explicitly flags the missing scheduling-side facts.

### Ground Truth Coverage

- Covered: la-prod-campaign-messages queue name and Zappa consumer handler (process_campaign_message_delivery) with citation
- Missing: CAMPAIGN_SQS / la-prod-campaign queue and its prod.py:31 reference
- Missing: producer campaigns/processor/campaign_event.py:33-58
- Missing: consumer campaigns/processor/campaign_event_processor.py:21-43
- Missing: producer campaigns/processor/user_messaging.py:425-469 for the messages queue
- Missing: la-prod-email queue from prod.ini:5 and email_sender.py:21-72

### Missing Or Weak Evidence

- No evidence item for la-prod-campaign queue despite retrieval step status 'found'
- No producer-side facts for either queue
- No la-prod-email delivery status queue evidence
- Only one of multiple expected edges is represented

### Answer Issues

- Answer is necessarily incomplete because evidence is missing; it does not fabricate but omits roughly two-thirds of the ground truth (scheduling queue, producers, email queue).

### Recommended Next Action

Fix retrieval to actually return facts for la-prod-campaign and la-prod-email channels, and add producer-side relationships (CAMPAIGN_SQS settings refs and processor/user_messaging senders) so the full scheduling→delivery→status chain can be synthesized.

## Q100 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

Evidence packet contains all documented v1 endpoints plus their backend matches/non-matches and client-call reconciliation results. The generated answer correctly identifies `/v1/collections` as the lone documented endpoint without an exact backend match (only a fuzzy match to `/v1/product_collections`) and reports that no documented endpoint has a confirmed client caller in the scoped clients reconciliation, with appropriate citations and caveats.

### Ground Truth Coverage

- Lists documented endpoints from openapi.yaml with line citations matching ground truth (lines 67-88).
- Identifies the `/v1/collections` -> `/v1/product_collections` drift as the principal mismatch (matches ground-truth drift call-out).
- Cites `/v1/store_data` implementation in `mercury_webhooks/app.py:101` (consistent with ground truth's `mercury_webhooks/app.py:100-104` placement, though the answer does not explicitly flag the cross-service nature as drift).
- Reports right_only status for all documented endpoints in the clients_vs_docs reconciliation, addressing the 'not called by any client' part of the question.

### Missing Or Weak Evidence

- Ground truth notes code-only `/v1/elementor` and `/v1/chatbot` not in docs; these are present in evidence (right_only in mercury-api) but the answer does not surface them. They are arguably out of scope for the user's specific question (documented endpoints), so this is not a real gap.

### Answer Issues

- Does not explicitly flag `/v1/store_data` as drift on the basis that it lives in mercury_webhooks rather than the main mercury_api backend, though the citation makes that visible.
- Treats client-call absence somewhat conservatively (rightly noted in caveats), but the binary 'zero matched' framing could over-state drift if CALLS_ENDPOINT facts simply weren't extracted.

### Recommended Next Action

Optionally extend the answer to call out `/v1/store_data` as a service-locality drift (webhooks vs main API) and to note code-only `/v1/elementor`/`/v1/chatbot` for completeness, even if outside the strict scope of the user's question.

## Q106 - Partial

**Evidence completeness:** partial

**Failure owner:** bad retrieval plan, missing KG fact

### Summary

The packet proves the consumer edge (handler, ARN, Zappa binding) but contains no producer send-site evidence and no reference to the downstream `la-prod-email` response queue. The answer faithfully reflects the packet, correctly refusing to name a producer, but consequently misses the ground-truth producer (mercury_api user_messaging.py + settings.CAMPAIGN_MESSAGE_SQS / prod.py:44) and the consumer's downstream emit.

### Ground Truth Coverage

- Consumer handler `mercury_campaign_messages.email_sender.process_campaign_message_delivery`: covered with citation.
- Queue ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages`: covered.
- Zappa wiring at `zappa_settings.json` ~L69-74: partially covered (cites L73 only).
- Producer file `mercury_api/campaigns/processor/user_messaging.py:425-469` and `settings.CAMPAIGN_MESSAGE_SQS`: not covered (explicitly refused).
- Prod setting `la-prod-campaign-messages` in `mercury_api/settings/prod.py:44`: not covered.
- Downstream emit to `la-prod-email` via `email_sender.py:21-72` and `configmanager/prod.ini:5`: not covered.

### Missing Or Weak Evidence

- No PRODUCES_EVENT / SQS SendMessage send-site fact tying mercury_api to la-prod-campaign-messages.
- No setting fact resolving `CAMPAIGN_MESSAGE_SQS` to `la-prod-campaign-messages` in `mercury_api/settings/prod.py`.
- No fact for the consumer's downstream production to `la-prod-email`.
- Retrieval plan only ran `event_channels` and `repo_dependencies`; no producer/send-site or settings lookup attempted.

### Answer Issues

- Refusal on producer is correct given the packet but leaves the user without the ground-truth producer.
- Does not mention the consumer's outgoing edge to `la-prod-email`, which is part of the ground-truth evidence chain.
- Cites only L73 instead of the L69-74 Zappa block.

### Recommended Next Action

Augment retrieval with a producer/send-site query (e.g., search for `CAMPAIGN_MESSAGE_SQS`, SQS send-site facts, and settings constants resolving to `la-prod-campaign-messages`) and add a downstream-emit lookup for the consumer to surface the `la-prod-email` edge.
