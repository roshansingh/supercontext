# LatticeAI Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/latticeai_23/goldset_packets_for_answers.json`
- Answers: `data/kg_runs/latticeai_23/goldset_answers.json`
- Model: `opus`
- Scenario count: 5
- Skipped missing ground truth: Q095

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q082 | complete | Pass | none | The EvidencePacket contains all the key facts in the ground truth: Apache vhost mapping `/` to `prod_shopagain_wsgi.py`, ServerName line, prod.ini api_url references in mercury_campaign_messages/mercury_tracking/mercury_webhooks, and env-driven clients in mercury_ui (REACT_APP_API_ROOT) and ShopAgainMobile (VITE_API_ROOT). The generated answer correctly identifies mercury_api as the backend, cites the WSGI entrypoint, and enumerates the env-driven clients with line-level citations. |
| Q083 | complete | Pass | none | Evidence packet contains all ground truth facts: backend auth/token routes in companies/urls.py at lines 60-64, mercury-ui auth.js callers (lines 14-56 covering logout/registration etc.), and ShopAgainMobile callers at login.api.tsx:6 and axiosConfig.tsx:37. The generated answer reproduces all of these with correct file paths and line citations. |
| Q088 | partial | Partial | missing KG fact, bad retrieval plan | The EvidencePacket only retrieved queue references from mercury_api settings and the Zappa consumer for la-prod-campaign-messages. It is missing the producer code paths (campaign_event.py, user_messaging.py), the consumer of la-prod-campaign (campaign_event_processor.py), and the entire la-prod-email delivery-status queue with its config and email_sender.py citations. The generated answer faithfully reports what the packet contains and discloses unknowns, but omits ground-truth facts not present in the packet. |
| Q100 | partial | Partial | missing KG fact | The packet captures the docs vs mercury_api comparison well, surfacing /v1/store_data as left_only and /v1/collections as a fuzzy match to /v1/product_collections. However, it misses the ground-truth fact that /v1/store_data is actually implemented in mercury_webhooks/app.py:100-104, so the answer wrongly concludes that endpoint is unimplemented anywhere. The packet also contains zero CALLS_ENDPOINT rows, so the 'no client caller' conclusion rests on absence-of-evidence rather than retrieved facts. |
| Q106 | partial | Partial | bad retrieval plan, missing KG fact | EvidencePacket establishes the consumer (Zappa handler process_campaign_message_delivery) and producer-side configuration in mercury_api prod settings, but lacks the actual producer send-site (user_messaging.py:425-469), the full SQS ARN, and the downstream la-prod-email emission. The answer faithfully synthesizes what the packet contains and explicitly flags the missing send-site and ARN as unknowns, but it cannot reconstruct the ground truth's producer code path or downstream edge. |

## Q082 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all the key facts in the ground truth: Apache vhost mapping `/` to `prod_shopagain_wsgi.py`, ServerName line, prod.ini api_url references in mercury_campaign_messages/mercury_tracking/mercury_webhooks, and env-driven clients in mercury_ui (REACT_APP_API_ROOT) and ShopAgainMobile (VITE_API_ROOT). The generated answer correctly identifies mercury_api as the backend, cites the WSGI entrypoint, and enumerates the env-driven clients with line-level citations.

### Ground Truth Coverage

- mercury_api as backend with WSGI entrypoint prod_shopagain_wsgi.py covered
- Apache vhost prod_shopagain.conf with ServerName api.shopagain.io covered
- mercury_campaign_messages/configmanager/prod.ini:8 covered
- mercury_tracking/common/configmanager/prod.ini:8 covered
- mercury_webhooks/common/configmanager/prod.ini:28 covered
- mercury_ui REACT_APP_API_ROOT covered (via .env.production, though GT cited src/services/api.js:10 which is not in packet)
- ShopAgainMobile VITE_API_ROOT covered (via .env files, though GT cited src/api/axiosConfig.tsx:8 which is not in packet)

### Missing Or Weak Evidence

- Ground truth specifically references mercury_ui/src/services/api.js:10 and ShopAgainMobile/src/api/axiosConfig.tsx:8; the packet instead provides the .env files where these env vars are defined. Substantively equivalent (env-driven clients) but exact source-of-use lines are not in the packet.

### Answer Issues

- Answer cites .env files rather than the client source files referenced in ground truth, but the conclusion (env-driven, not hard-coded) is clearly stated and supported.

### Recommended Next Action

Optionally augment retrieval to include client source files (api.js, axiosConfig.tsx) that consume the env vars, for stronger alignment with ground truth citations.

## Q083 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

Evidence packet contains all ground truth facts: backend auth/token routes in companies/urls.py at lines 60-64, mercury-ui auth.js callers (lines 14-56 covering logout/registration etc.), and ShopAgainMobile callers at login.api.tsx:6 and axiosConfig.tsx:37. The generated answer reproduces all of these with correct file paths and line citations.

### Ground Truth Coverage

- Backend auth/ at companies/urls.py:60 cited
- Backend auth/registration/ at companies/urls.py:61-62 cited
- JWT api/token/ at companies/urls.py:63 cited
- JWT api/token/refresh/ at companies/urls.py:64 cited
- Web caller mercury_ui/src/services/auth.js cited (lines 14, 23, 27, etc., spanning the 5-27 ground truth range and beyond)
- Mobile caller ShopAgainMobile/src/api/login.api.tsx:6 for /api/token/ cited
- Mobile caller ShopAgainMobile/src/api/axiosConfig.tsx:37 for /api/token/refresh/ cited

### Missing Or Weak Evidence

- Ground truth references auth.js:5-27 (login/logout/registration). Packet shows logout at L14, user PATCH at L23, registration at L27 but no explicit login call at L5; the answer doesn't claim a login call either, so no distortion.

### Answer Issues

- Answer includes some extra integration.js endpoints (ggl/judge_me) not strictly in the ground truth scope, but they are properly cited and don't distort the core answer.

### Recommended Next Action

Accept the result; optionally verify whether mercury-ui has a /api/token/ login caller that may be missing from the packet (ground truth implies login is in auth.js but does not specify a JWT endpoint there).

## Q088 - Partial

**Evidence completeness:** partial

**Failure owner:** missing KG fact, bad retrieval plan

### Summary

The EvidencePacket only retrieved queue references from mercury_api settings and the Zappa consumer for la-prod-campaign-messages. It is missing the producer code paths (campaign_event.py, user_messaging.py), the consumer of la-prod-campaign (campaign_event_processor.py), and the entire la-prod-email delivery-status queue with its config and email_sender.py citations. The generated answer faithfully reports what the packet contains and discloses unknowns, but omits ground-truth facts not present in the packet.

### Ground Truth Coverage

- Covered: la-prod-campaign queue named and cited at mercury_api/settings/prod.py:31 (CAMPAIGN_SQS).
- Covered: la-prod-campaign-messages queue named and cited at mercury_api/settings/prod.py:44 (CAMPAIGN_MESSAGE_SQS).
- Covered: Consumer handler mercury_campaign_messages.email_sender.process_campaign_message_delivery via zappa_settings.json (line 73, ground truth says 69-74).
- Missing: Producer campaigns/processor/campaign_event.py:33-58 for la-prod-campaign.
- Missing: Consumer campaigns/processor/campaign_event_processor.py:21-43 for la-prod-campaign.
- Missing: Producer campaigns/processor/user_messaging.py:425-469 for la-prod-campaign-messages.
- Missing: la-prod-email delivery status queue, configmanager/prod.ini:5, and email_sender.py:21-72.

### Missing Or Weak Evidence

- No PRODUCES_EVENT facts for either queue (no campaign_event.py or user_messaging.py references).
- No CONSUMES_EVENT fact for la-prod-campaign (campaign_event_processor.py).
- Entire third queue (la-prod-email) and its associated producer/config citations absent.
- Retrieval plan only queried the two campaign queues; did not search for la-prod-email or producer call sites.

### Answer Issues

- Does not mention la-prod-email or the delivery-status leg of the pipeline.
- Does not identify producer source files (campaign_event.py, user_messaging.py) — though correctly flagged as unknown.
- Does not identify campaign_event_processor.py as consumer of la-prod-campaign — correctly flagged as unknown.
- Speculative 'fan-out' arrow in the Flow diagram is not supported by any evidence.

### Recommended Next Action

Extend retrieval to include producer/consumer code references (PRODUCES_EVENT/CONSUMES_EVENT for campaigns/processor/*) and add a third event_channels query for la-prod-email plus configmanager/prod.ini, then resynthesize.

## Q100 - Partial

**Evidence completeness:** partial

**Failure owner:** missing KG fact

### Summary

The packet captures the docs vs mercury_api comparison well, surfacing /v1/store_data as left_only and /v1/collections as a fuzzy match to /v1/product_collections. However, it misses the ground-truth fact that /v1/store_data is actually implemented in mercury_webhooks/app.py:100-104, so the answer wrongly concludes that endpoint is unimplemented anywhere. The packet also contains zero CALLS_ENDPOINT rows, so the 'no client caller' conclusion rests on absence-of-evidence rather than retrieved facts.

### Ground Truth Coverage

- Documented /v1 paths from openapi.yaml lines 67-88 are enumerated in evidence and answer.
- Backend implementations from mercury_api/urls.py:50-58 are enumerated, including code-only /v1/elementor and /v1/chatbot.
- /v1/collections vs /v1/product_collections rename drift is captured with similarity 0.789 and cited in the answer.
- Missing: /v1/store_data being implemented in mercury_webhooks/app.py:100-104 is not in the packet and not in the answer.

### Missing Or Weak Evidence

- No EXPOSES_ENDPOINT fact for /v1/store_data in mercury_webhooks/app.py:100-104, even though that path is listed for other mercury_webhooks routes (/v1/sendgrid, /v1/stripe).
- No CALLS_ENDPOINT facts from any client repo were retrieved; the right_only labels in clients_vs_docs cannot be substantiated from the packet.
- Code-only /v1/elementor and /v1/chatbot are present as right_only but the answer's question scope drops them (acceptable, since the question asks about documented endpoints).

### Answer Issues

- States /v1/store_data has no backend route at all; ground truth says it is implemented in mercury_webhooks/app.py:100-104, just not in the main API. The answer should have caveated this rather than declared it unimplemented.
- Lists every documented /v1 endpoint as 'not called by any scoped client' based purely on right_only labels without any retrieved CALLS_ENDPOINT rows; this is appropriately caveated but still over-asserted.
- Does not call out the asymmetry that the packet surfaced no mercury_webhooks /v1/store_data fact, which would have been the right way to flag the gap.

### Recommended Next Action

Augment the retrieval to include all mercury_webhooks EXPOSES_ENDPOINT facts (or expand path filters beyond /v1/sendgrid|/v1/stripe) so /v1/store_data's implementation in mercury_webhooks is reconciled, and add CALLS_ENDPOINT facts from client repos to substantiate (or refute) the right_only client-call gaps.

## Q106 - Partial

**Evidence completeness:** partial

**Failure owner:** bad retrieval plan, missing KG fact

### Summary

EvidencePacket establishes the consumer (Zappa handler process_campaign_message_delivery) and producer-side configuration in mercury_api prod settings, but lacks the actual producer send-site (user_messaging.py:425-469), the full SQS ARN, and the downstream la-prod-email emission. The answer faithfully synthesizes what the packet contains and explicitly flags the missing send-site and ARN as unknowns, but it cannot reconstruct the ground truth's producer code path or downstream edge.

### Ground Truth Coverage

- Covered: settings.CAMPAIGN_MESSAGE_SQS reference in mercury_api/settings/prod.py:44 (and other prod variants).
- Covered: consumer handler mercury_campaign_messages.email_sender.process_campaign_message_delivery wired via zappa_settings.json (line 73; GT cites 69-74).
- Covered: queue name la-prod-campaign-messages.
- Not covered: producer send-site at mercury_api/campaigns/processor/user_messaging.py:425-469 sending queueMessage.
- Not covered: full ARN arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages.
- Not covered: downstream emission to la-prod-email via email_sender.py:21-72 and configmanager/prod.ini:5.

### Missing Or Weak Evidence

- No SENDS_TO/PRODUCES fact pointing to mercury_api/campaigns/processor/user_messaging.py:425-469.
- No fact carrying the resolved SQS ARN string (only a generic sqs_arn source_kind reference).
- No evidence of the consumer's downstream emission to la-prod-email.

### Answer Issues

- Misses the producer code path that ground truth says exists (user_messaging.py:425-469); answer treats it as not indexed rather than not retrieved.
- Does not surface the downstream la-prod-email edge from the consumer, which is part of the broader edge picture (though arguably outside the asked queue).

### Recommended Next Action

Augment the retrieval plan with a producer-side code search for callers of settings.CAMPAIGN_MESSAGE_SQS / SendMessage to la-prod-campaign-messages within mercury_api, and include ARN-resolution and downstream channel facts (la-prod-email) for the consumer.
