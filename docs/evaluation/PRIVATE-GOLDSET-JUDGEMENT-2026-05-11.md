# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/private_goldset_eval_2026_05_11/goldset_packets_eval_2026_05_11.json`
- Answers: `data/kg_runs/private_goldset_eval_2026_05_11/goldset_answers_eval_2026_05_11.json`
- Model: `opus`
- Scenario count: 6
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q082 | complete | Pass | none | The evidence packet contains all ground truth facts: the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py, the configmanager prod.ini references in mercury_campaign_messages/mercury_tracking/mercury_webhooks, mercury_ui's REACT_APP_API_ROOT in src/services/api.js:10, and ShopAgainMobile's VITE_API_ROOT in src/api/axiosConfig.tsx:8. The answer accurately reports each of these with line-level citations and correctly identifies mercury_api as the backend. |
| Q083 | partial | Partial | missing KG fact, bad retrieval plan | Backend auth/token routes are well-covered in the evidence packet and reproduced in the answer with correct file/line citations. However, the packet contains no web caller facts (mercury_ui/src/services/auth.js) and only one mobile caller (axiosConfig.tsx:37 for /api/token/refresh/), missing ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/. The answer correctly acknowledges these gaps but cannot fully reconstruct the ground truth. |
| Q088 | complete | Pass | none | The EvidencePacket contains the key facts to reconstruct the ground truth: producer/consumer pairs for la-prod-campaign, la-prod-campaign-messages (with Zappa event source), and la-prod-email (delivery status). The generated answer covers all three required queues with producers, consumers, and Zappa citation, and adds an extra email-activity edge as caveated lineage. |
| Q095 | complete | Pass | none | Evidence packet contains the domain-to-WSGI mapping, the mercury_api backend binding, and all client/config references named in the ground truth. The generated answer covers each ground-truth element with precise citations. |
| Q100 | complete | Pass | none | The EvidencePacket contains the documented endpoints (openapi.yaml lines 67-88 and dist.json variants), the mercury_api routes (urls.py 50-58), the /v1/store_data implementation in mercury_webhooks/app.py:101, the possible_match for /v1/collections↔/v1/product_collections, and the right_only client_vs_docs rows. The answer reconstructs the ground-truth diff: it lists the documented public paths, flags /v1/collections→/v1/product_collections drift, calls out /v1/store_data placement in mercury_webhooks rather than mercury_api, and notes /v1/elementor and /v1/chatbot as code-only/undocumented. |
| Q106 | complete | Pass | none | The EvidencePacket contains the producer (user_messaging.py:469), the Zappa-bound consumer handler (process_campaign_message_delivery) with the full SQS ARN, and the downstream la-prod-email production/consumption. The generated answer correctly identifies producer, consumer, queue ARN, and edge proof matching the ground truth. |

## Q082 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The evidence packet contains all ground truth facts: the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py, the configmanager prod.ini references in mercury_campaign_messages/mercury_tracking/mercury_webhooks, mercury_ui's REACT_APP_API_ROOT in src/services/api.js:10, and ShopAgainMobile's VITE_API_ROOT in src/api/axiosConfig.tsx:8. The answer accurately reports each of these with line-level citations and correctly identifies mercury_api as the backend.

### Ground Truth Coverage

- Apache vhost prod_shopagain.conf maps / to mercury_api/prod_shopagain_wsgi.py (covered)
- ServerName api.shopagain.io at line 7 (covered via L2-L7 mapping citation)
- mercury_campaign_messages prod.ini:8 reference (covered)
- mercury_tracking prod.ini:8 reference (covered)
- mercury_webhooks prod.ini:28 reference (covered)
- mercury_ui REACT_APP_API_ROOT in src/services/api.js:10 (covered)
- ShopAgainMobile VITE_API_ROOT in src/api/axiosConfig.tsx:8 (covered)
- Env-driven clients vs hard-coded (covered, with caveat about minified storefront scripts)

### Missing Or Weak Evidence

- None.

### Answer Issues

- None.

### Recommended Next Action

Accept the result; no remediation needed.

## Q083 - Partial

**Evidence completeness:** partial

**Failure owner:** missing KG fact, bad retrieval plan

### Summary

Backend auth/token routes are well-covered in the evidence packet and reproduced in the answer with correct file/line citations. However, the packet contains no web caller facts (mercury_ui/src/services/auth.js) and only one mobile caller (axiosConfig.tsx:37 for /api/token/refresh/), missing ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/. The answer correctly acknowledges these gaps but cannot fully reconstruct the ground truth.

### Ground Truth Coverage

- Covered: auth/ and auth/registration/ at lines 60-62 in companies/urls.py
- Covered: api/token/ and api/token/refresh/ at lines 63-64 in companies/urls.py
- Covered: ShopAgainMobile/src/api/axiosConfig.tsx:37 for /api/token/refresh/
- Missing: mercury_ui/src/services/auth.js:5-27 (web login/logout/registration callers)
- Missing: ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/

### Missing Or Weak Evidence

- No web caller evidence for mercury_ui/src/services/auth.js
- No mobile caller evidence for ShopAgainMobile/src/api/login.api.tsx (login endpoint)

### Answer Issues

- Omits web caller mercury_ui/src/services/auth.js (not in evidence packet)
- Omits mobile login caller ShopAgainMobile/src/api/login.api.tsx (not in evidence packet)

### Recommended Next Action

Expand retrieval to query callers of /api/token/ and /auth/* endpoints across web (mercury_ui) and mobile (ShopAgainMobile) repos, including login endpoints, not just token refresh.

## Q088 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains the key facts to reconstruct the ground truth: producer/consumer pairs for la-prod-campaign, la-prod-campaign-messages (with Zappa event source), and la-prod-email (delivery status). The generated answer covers all three required queues with producers, consumers, and Zappa citation, and adds an extra email-activity edge as caveated lineage.

### Ground Truth Coverage

- la-prod-campaign: producer campaign_event.py and consumer campaign_event_processor.py cited with line refs
- la-prod-campaign-messages: producer user_messaging.py:469 and Zappa-bound consumer mercury_campaign_messages.email_sender.process_campaign_message_delivery cited
- la-prod-email: producer email_sender.py:71 with prod.ini:5 reference for delivery status

### Missing Or Weak Evidence

- Ground truth cites mercury_api/settings/prod.py:31 and :44 for CAMPAIGN_SQS/CAMPAIGN_MESSAGE_SQS definitions; evidence lists these as literal_ref sources without exact line numbers, but the resolved values are present.
- Zappa line range in ground truth is 69-74; evidence cites line 73, which is within range.

### Answer Issues

- Answer adds an extra la-prod-email-activity section not in ground truth, but it's appropriately caveated as downstream fan-out and does not distort the primary chain.
- Settings file line numbers (prod.py:31, :44) not explicitly cited, though the symbol resolution is shown.

### Recommended Next Action

Accept as Pass; optionally enhance retrieval to surface explicit settings/prod.py line citations for CAMPAIGN_SQS and CAMPAIGN_MESSAGE_SQS to fully mirror ground truth references.

## Q095 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

Evidence packet contains the domain-to-WSGI mapping, the mercury_api backend binding, and all client/config references named in the ground truth. The generated answer covers each ground-truth element with precise citations.

### Ground Truth Coverage

- api.shopagain.io → /home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py via apache/prod_shopagain.conf:2-7 (covered)
- Backend repo mercury_api identified (covered)
- mercury_ui REACT_APP_API_ROOT=https://api.shopagain.io/ (covered)
- ShopAgainMobile VITE_API_ROOT=https://api.shopagain.io (covered)
- mercury_campaign_messages/configmanager/prod.ini:8 (covered)
- mercury_tracking/common/configmanager/prod.ini:8 (covered)
- mercury_webhooks/common/configmanager/prod.ini:28 (covered)

### Missing Or Weak Evidence

- None.

### Answer Issues

- None.

### Recommended Next Action

Accept as Pass; no remediation needed.

## Q100 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains the documented endpoints (openapi.yaml lines 67-88 and dist.json variants), the mercury_api routes (urls.py 50-58), the /v1/store_data implementation in mercury_webhooks/app.py:101, the possible_match for /v1/collections↔/v1/product_collections, and the right_only client_vs_docs rows. The answer reconstructs the ground-truth diff: it lists the documented public paths, flags /v1/collections→/v1/product_collections drift, calls out /v1/store_data placement in mercury_webhooks rather than mercury_api, and notes /v1/elementor and /v1/chatbot as code-only/undocumented.

### Ground Truth Coverage

- Documented paths listed: /v1/company, /v1/contacts, /v1/products, /v1/collections, /v1/carts, /v1/checkouts, /v1/orders, /v1/store_data (with openapi.yaml line citations).
- Backend implementations enumerated in mercury_api/urls.py (lines 50-58) including /v1/product_collections, /v1/elementor, /v1/chatbot.
- Drift /v1/collections vs /v1/product_collections (fuzzy match, similarity 0.789) called out.
- /v1/store_data implemented in mercury_webhooks/app.py:101 explicitly flagged as service placement drift.
- Code-only /v1/elementor and /v1/chatbot noted as undocumented backend routes.

### Missing Or Weak Evidence

- Packet contains zero CALLS_ENDPOINT facts from the client repos, so the 'no obvious caller' claim rests on absence of evidence; the answer correctly acknowledges this caveat.

### Answer Issues

- Frames every documented endpoint as having 'no obvious caller' because all docs rows appear as right_only in clients_vs_docs — this could overstate drift, but the answer flags the limitation in caveats.

### Recommended Next Action

Re-run retrieval to include CALLS_ENDPOINT facts from mercury_ui, ShopAgainMobile, and shopagain-chat-widget so caller coverage can be verified rather than inferred from absence.

## Q106 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains the producer (user_messaging.py:469), the Zappa-bound consumer handler (process_campaign_message_delivery) with the full SQS ARN, and the downstream la-prod-email production/consumption. The generated answer correctly identifies producer, consumer, queue ARN, and edge proof matching the ground truth.

### Ground Truth Coverage

- Producer mercury_api/campaigns/processor/user_messaging.py with settings.CAMPAIGN_MESSAGE_SQS resolving to la-prod-campaign-messages is cited (line 469 within the GT 425-469 range).
- Consumer mercury_campaign_messages.email_sender.process_campaign_message_delivery wired via zappa_settings.json to ARN arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages is cited.
- Downstream production to la-prod-email by email_sender.py:71 with prod.ini:5 resolution is included.

### Missing Or Weak Evidence

- Exact producer line range 425-469 is represented only by send_message line 469; full function span not explicitly given but is sufficient.
- Explicit prod.py:44 setting line for la-prod-campaign-messages is not cited, though the literal resolution from settings.prod.CAMPAIGN_MESSAGE_SQS is shown.

### Answer Issues

- None.

### Recommended Next Action

Accept as Pass; optionally enrich evidence with the explicit settings/prod.py line for the CAMPAIGN_MESSAGE_SQS literal.
