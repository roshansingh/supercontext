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
| Q082 | complete | Pass | none | Evidence packet contains the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py and ServerName api.shopagain.io, the three backend service prod.ini references, and both client env-var entrypoints (REACT_APP_API_ROOT in mercury_ui/src/services/api.js:10 and VITE_API_ROOT in ShopAgainMobile/src/api/axiosConfig.tsx:8). The generated answer correctly identifies mercury_api as the backend with the WSGI entrypoint and enumerates the env-driven clients plus sibling services, matching the ground truth. |
| Q083 | complete | Pass | none | The EvidencePacket contains all facts in the Ground Truth: companies/urls.py lines 60-64 for auth/token routes, mercury_ui/src/services/auth.js auth callers, and ShopAgainMobile login.api.tsx:6 and axiosConfig.tsx:37 mobile callers. The generated answer correctly identifies the backend JWT token routes, the affected mobile callers with precise file/line citations, and provides the adjacent /auth/* surface (web callers in mercury_ui/src/services/auth.js) for completeness. |
| Q088 | complete | Pass | none | The EvidencePacket contains all key facts required by the ground truth: CAMPAIGN_SQS producer/consumer, CAMPAIGN_MESSAGE_SQS producer and Zappa-bound consumer, and la-prod-email producer with config reference. The generated answer faithfully cites these and adds a downstream email-activity hop without distorting the core lineage. |
| Q095 | complete | Pass | none | The EvidencePacket contains the Apache vhost routing api.shopagain.io to prod_shopagain_wsgi.py (target repo mercury_api), and references to api.shopagain.io across mercury_ui (REACT_APP_API_ROOT), ShopAgainMobile (VITE_API_ROOT), mercury_campaign_messages, mercury_tracking, and mercury_webhooks prod.ini files at the exact lines named in the ground truth. The generated answer covers all ground-truth elements and adds supplementary references that are also evidenced. |
| Q100 | complete | Pass | none | The evidence packet contains all the facts needed: documented endpoints in shopagain_api_docs (company, contacts, products, collections, carts, checkouts, orders, store_data), backend implementations in mercury_api/urls.py (with /v1/product_collections, /v1/elementor, /v1/chatbot as right_only), the matched /v1/store_data in mercury_webhooks/app.py:101, and the fuzzy /v1/collections vs /v1/product_collections drift. The answer correctly identifies /v1/collections as the documented-but-not-obviously-implemented case, notes the /v1/store_data placement drift to mercury_webhooks, and lists all documented endpoints lacking client callers, with citations. |
| Q106 | complete | Pass | none | The EvidencePacket contains the producer send-site (user_messaging.py:469), Zappa-bound consumer handler with the full queue ARN, and the downstream la-prod-email producer/consumer edges. The generated answer accurately reflects the producer, consumer, queue ARN, and downstream lineage with correct citations. |

## Q082 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

Evidence packet contains the Apache vhost mapping to mercury_api's prod_shopagain_wsgi.py and ServerName api.shopagain.io, the three backend service prod.ini references, and both client env-var entrypoints (REACT_APP_API_ROOT in mercury_ui/src/services/api.js:10 and VITE_API_ROOT in ShopAgainMobile/src/api/axiosConfig.tsx:8). The generated answer correctly identifies mercury_api as the backend with the WSGI entrypoint and enumerates the env-driven clients plus sibling services, matching the ground truth.

### Ground Truth Coverage

- Backend mercury_api with WSGI prod_shopagain_wsgi.py and ServerName api.shopagain.io — covered (apache/prod_shopagain.conf L2-7).
- mercury_campaign_messages/configmanager/prod.ini:8 — covered.
- mercury_tracking/common/configmanager/prod.ini:8 — covered.
- mercury_webhooks/common/configmanager/prod.ini:28 — covered.
- mercury_ui REACT_APP_API_ROOT in src/services/api.js:10 — covered.
- ShopAgainMobile VITE_API_ROOT in src/api/axiosConfig.tsx:8 — covered.
- Docs references — covered via shopagain_api_docs entries.

### Missing Or Weak Evidence

- None.

### Answer Issues

- None.

### Recommended Next Action

Accept the answer as-is; no additional retrieval needed.

## Q083 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all facts in the Ground Truth: companies/urls.py lines 60-64 for auth/token routes, mercury_ui/src/services/auth.js auth callers, and ShopAgainMobile login.api.tsx:6 and axiosConfig.tsx:37 mobile callers. The generated answer correctly identifies the backend JWT token routes, the affected mobile callers with precise file/line citations, and provides the adjacent /auth/* surface (web callers in mercury_ui/src/services/auth.js) for completeness.

### Ground Truth Coverage

- Backend api/token/ at companies/urls.py:63 cited
- Backend api/token/refresh/ at companies/urls.py:64 cited
- Backend auth/ at companies/urls.py:60 cited (adjacent section)
- Backend auth/registration/ at companies/urls.py:61-62 cited (adjacent section)
- Web caller mercury_ui/src/services/auth.js cited for logout/user/registration (lines 14, 23, 27)
- Mobile caller ShopAgainMobile/src/api/login.api.tsx:6 cited
- Mobile caller ShopAgainMobile/src/api/axiosConfig.tsx:37 cited

### Missing Or Weak Evidence

- Evidence does not include the auth.js lines 5-12 explicitly (login function); the earliest auth.js line shown is 14 (logout). Ground truth references 'auth.js:5-27' for login/logout/registration but only logout (14), user (23), and registration (27) lines appear in the packet.

### Answer Issues

- Answer narrows the impact to JWT /api/token/* and relegates /auth/* to an 'adjacent' section, while the ground truth treats both as part of the 'token auth endpoints' scope; however coverage is still present.

### Recommended Next Action

Accept as Pass. Optionally enrich the retrieval to capture auth.js login (around line 5) to fully mirror the ground truth's 5-27 range.

## Q088 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all key facts required by the ground truth: CAMPAIGN_SQS producer/consumer, CAMPAIGN_MESSAGE_SQS producer and Zappa-bound consumer, and la-prod-email producer with config reference. The generated answer faithfully cites these and adds a downstream email-activity hop without distorting the core lineage.

### Ground Truth Coverage

- la-prod-campaign queue with producer campaign_event.py and consumer campaign_event_processor.py covered
- la-prod-campaign-messages produced by user_messaging.py and consumed via Zappa-bound mercury_campaign_messages.email_sender.process_campaign_message_delivery covered
- la-prod-email written by email_sender.py with prod.ini reference covered
- Settings module references for CAMPAIGN_SQS / CAMPAIGN_MESSAGE_SQS noted via resolution metadata

### Missing Or Weak Evidence

- Ground truth cites specific settings file lines (e.g., mercury_api/settings/prod.py:31, :44); evidence references the settings modules collectively rather than exact line numbers, but the underlying facts are present.
- Ground truth cites campaign_event_processor.py:21-43; evidence shows line 25 only — same function, narrower citation.

### Answer Issues

- Answer adds la-prod-email-activity as a fourth hop which is beyond the ground truth scope but does not contradict it.

### Recommended Next Action

Accept the result; optionally tighten retrieval to surface exact settings.py line numbers for tighter citation alignment with ground truth.

## Q095 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains the Apache vhost routing api.shopagain.io to prod_shopagain_wsgi.py (target repo mercury_api), and references to api.shopagain.io across mercury_ui (REACT_APP_API_ROOT), ShopAgainMobile (VITE_API_ROOT), mercury_campaign_messages, mercury_tracking, and mercury_webhooks prod.ini files at the exact lines named in the ground truth. The generated answer covers all ground-truth elements and adds supplementary references that are also evidenced.

### Ground Truth Coverage

- api.shopagain.io → /home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py via ansible-playbooks/apache/prod_shopagain.conf:2-7 (covered)
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

Accept the answer as Pass; no further action needed.

## Q100 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The evidence packet contains all the facts needed: documented endpoints in shopagain_api_docs (company, contacts, products, collections, carts, checkouts, orders, store_data), backend implementations in mercury_api/urls.py (with /v1/product_collections, /v1/elementor, /v1/chatbot as right_only), the matched /v1/store_data in mercury_webhooks/app.py:101, and the fuzzy /v1/collections vs /v1/product_collections drift. The answer correctly identifies /v1/collections as the documented-but-not-obviously-implemented case, notes the /v1/store_data placement drift to mercury_webhooks, and lists all documented endpoints lacking client callers, with citations.

### Ground Truth Coverage

- Lists all 8 documented public paths from openapi.yaml (company, contacts, products, collections, carts, checkouts, orders, store_data)
- Identifies docs `/v1/collections` maps to code `/v1/product_collections` (drift with fuzzy similarity 0.789)
- Identifies docs `/v1/store_data` is implemented in mercury_webhooks/app.py:101 rather than the main mercury_api backend
- Mentions code-only `/v1/elementor` and `/v1/chatbot` in caveats as inverse drift

### Missing Or Weak Evidence

- No explicit CALLS_ENDPOINT facts for clients (mercury_ui, ShopAgainMobile, shopagain-chat-widget) — answer correctly flags this as ambiguous in caveats
- Ground truth references mercury_api/urls.py:50-58 and mercury_webhooks/app.py:100-104; packet line numbers slightly differ but are consistent (101 for store_data)

### Answer Issues

- Answer's framing of 'all eight documented v1 resources have no client caller' depends on whether absent CALLS_ENDPOINT facts mean truly uncalled vs not-extracted; the answer appropriately caveats this

### Recommended Next Action

Add CALLS_ENDPOINT extraction (or confirm absence) for the listed client repos to distinguish 'no caller' from 'no data', and consider mapping `/v1/collections` ↔ `/v1/product_collections` as a known alias to remove the false-positive drift.

## Q106 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains the producer send-site (user_messaging.py:469), Zappa-bound consumer handler with the full queue ARN, and the downstream la-prod-email producer/consumer edges. The generated answer accurately reflects the producer, consumer, queue ARN, and downstream lineage with correct citations.

### Ground Truth Coverage

- Producer `campaigns.processor.user_messaging` sending via `settings.CAMPAIGN_MESSAGE_SQS` to `la-prod-campaign-messages` is cited (line 469).
- Consumer `mercury_campaign_messages.email_sender.process_campaign_message_delivery` wired via zappa_settings.json (line 73) to ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` is cited.
- Downstream emission to `la-prod-email` via `email_sender.py:71` and prod.ini reference is included.

### Missing Or Weak Evidence

- Exact line range 425-469 for the producer is narrowed to L469 only (single line) in evidence; ground truth cites a broader span.
- Prod settings file `mercury_api/settings/prod.py:44` is referenced only generically via the `literal_ref` source list, without explicit line number.
- `email_sender.py:21-72` range is collapsed to L71 in evidence; functional but narrower.

### Answer Issues

- Minor: line ranges are collapsed to single lines rather than full ground-truth spans, but coordinates still point to correct files.

### Recommended Next Action

Accept the result; optionally enrich evidence with broader line spans for producer/consumer function bodies and explicit settings file line numbers for tighter coordinate fidelity.
