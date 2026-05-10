# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/latticeai_23_event_eval_2026_05_10`
- Model: `opus`
- Scenario count: 3

## Summary

| Scenario | Score | Failure Modes | Notes |
|---|---|---|---|
| Q088 | Pass | none | Answer enumerates each queue connecting scheduling to delivery, identifies producers and consumers with file/line citations, and includes the Zappa event source — matching the expected shape. |
| Q095 | Pass | none | Answer covers all three components of the expected shape: domain-to-WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), client baseURLs pointing to that domain (ShopAgainMobile, mercury_ui, mercury_campaign_messages, mercury_tracking, mercury_webhooks, shopagain_api_docs), and backend repo evidence (mercury_api settings), all with file/line citations. |
| Q106 | Pass | none | Provides producer call site, Zappa-bound consumer handler, queue ARN/name, and lists explicit unknowns, matching the expected answer shape with citations. |

## Q088 - Pass

**Question:** Which SQS queues connect campaign scheduling to message delivery, and who consumes each queue?

### Answer

## SQS queues linking campaign scheduling to message delivery

### 1. `la-prod-campaign` — campaign scheduling queue
- **Producer:** `campaigns.processor.campaign_event.send_event_to_campaign_queue` via `settings.CAMPAIGN_SQS` [mercury_api/campaigns/processor/campaign_event.py:L58-L58].
- **Consumer:** `campaigns.processor.campaign_event_processor.consume_campaign_queue` (long-poll `receive_messages`) [mercury_api/campaigns/processor/campaign_event_processor.py:L25-L25].

### 2. `la-prod-campaign-messages` — fan-out to message-delivery service
- **Producer:** `campaigns.processor.user_messaging.send_email_to_queue` via `settings.CAMPAIGN_MESSAGE_SQS` [mercury_api/campaigns/processor/user_messaging.py:L469-L469].
- **Consumer:** `mercury-campaign-messages` Lambda, wired through Zappa event source ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` to handler `mercury_campaign_messages.email_sender.process_campaign_message_delivery` [mercury_campaign_messages/zappa_settings.json:L73-L73].

### 3. `la-prod-email` — outbound email delivery queue
- **Config reference:** `EMAIL_QUEUE=la-prod-email` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L5-L5].
- **Producer:** `mercury_campaign_messages.email_sender.process_campaign_message_delivery` via `config.queueConfig.EMAIL_QUEUE` [mercury_campaign_messages/mercury_campaign_messages/email_sender.py:L71-L71].
- **Consumer:** `campaigns.processor.email_queue_processor.consume_email_queue` (uses `EMAIL_SQS`) [mercury_api/campaigns/processor/email_queue_processor.py:L24-L24].

### 4. `la-prod-email-activity` — delivery-status / activity feedback queue
- **Config reference:** `EMAIL_ACTIVITY_QUEUE=la-prod-email-activity` [mercury_webhooks/common/configmanager/prod.ini:L19-L19].
- **Producers (mercury_webhooks):**
  - `views.ElasticEmail.ElasticEmailView.get` [mercury_webhooks/views/ElasticEmail.py:L56-L56]
  - `views.EmailActivity.EmailActivityView.post` [mercury_webhooks/views/EmailActivity.py:L67-L67]
- **Consumer:** `stores.event_processor.email_activity_processor.consume_email_activity_queue` [mercury_api/stores/event_processor/email_activity_processor.py:L234-L234].

### End-to-end flow
`campaign_event → la-prod-campaign → consume_campaign_queue → user_messaging → la-prod-campaign-messages → mercury-campaign-messages (Zappa SQS trigger) → la-prod-email → consume_email_queue` and webhook callbacks → `la-prod-email-activity → consume_email_activity_queue`.

### Caveats

- Queue literals resolve to dev/staging/prod variants depending on settings module; only the prod values are cited here.
- `mercury-campaign-messages` consumption of `la-prod-campaign-messages` is via an authoritative Zappa event source rather than an explicit `receive_messages` call.

### Unknown Because Missing Evidence

- None.

### Score Notes

Answer enumerates each queue connecting scheduling to delivery, identifies producers and consumers with file/line citations, and includes the Zappa event source — matching the expected shape.

## Q095 - Pass

**Question:** If prod_shopagain_wsgi.py deployment changes, which public domains and clients are impacted?

### Answer

## Impact Analysis: `prod_shopagain_wsgi.py`

### Public Domain Routed to This WSGI
- **`api.shopagain.io`** → `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py`, configured via Apache vhost [ansible-playbooks/apache/prod_shopagain.conf:L2-L7].

### Backend Repo Served
- **`mercury_api`** — production settings bind this domain via `API_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L2], `SMS_WEBHOOK_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L4], `CSRF_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L48], and `SESSION_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L49].

### Clients / Configs That Call `api.shopagain.io` (Impacted on Outage or Breaking Change)
- **ShopAgainMobile** — `VITE_API_ROOT=https://api.shopagain.io` in both [ShopAgainMobile/.env.development:L1] and [ShopAgainMobile/.env.production:L1].
- **mercury_ui** — `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1]; embedded scripts/widgets [mercury_ui/public/shopagain_script.min.js:L1], [mercury_ui/public/shopify/shopagain_script.js:L32], [mercury_ui/public/shopify/shopagain_script.min.js:L1], [mercury_ui/public/shopify/widgets.js:L31].
- **mercury_campaign_messages** — `api_url=https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8].
- **mercury_tracking** — `api_url=https://api.shopagain.io` [mercury_tracking/common/configmanager/prod.ini:L8].
- **mercury_webhooks** — `api_url=https://api.shopagain.io` [mercury_webhooks/common/configmanager/prod.ini:L28].
- **shopagain_api_docs** (acme-api) — references the domain in [shopagain_api_docs/dist.json:L14], [shopagain_api_docs/dist.json:L60], [shopagain_api_docs/docs/dist.json:L18], and [shopagain_api_docs/openapi/openapi.yaml:L45].

### Summary
A change to `prod_shopagain_wsgi.py` directly affects the `mercury_api` backend exposed at `api.shopagain.io`. Downstream impact spans the mobile client (ShopAgainMobile), the web/Shopify widget UI (mercury_ui), three internal services (mercury_campaign_messages, mercury_tracking, mercury_webhooks), and the public API docs (shopagain_api_docs). Cookie/session domains (`CSRF_COOKIE_DOMAIN`, `SESSION_COOKIE_DOMAIN`) are also pinned to this host, so auth/session continuity is at risk.

### Caveats

- Only static-config evidence; does not include runtime traffic or services that resolve the domain dynamically.
- `shopagain_api_docs` references are documentation/spec artifacts, so impact there is informational rather than runtime.

### Unknown Because Missing Evidence

- Whether any non-prod environments share this WSGI target.
- Specific endpoints/routes within mercury_api that would break vs. degrade.

### Score Notes

Answer covers all three components of the expected shape: domain-to-WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), client baseURLs pointing to that domain (ShopAgainMobile, mercury_ui, mercury_campaign_messages, mercury_tracking, mercury_webhooks, shopagain_api_docs), and backend repo evidence (mercury_api settings), all with file/line citations.

## Q106 - Pass

**Question:** For la-prod-campaign-messages, who produces messages, who consumes them, and what evidence proves the edge?

### Answer

## Producer (sqs:la-prod-campaign-messages)
- `campaigns.processor.user_messaging.send_email_to_queue` sends to the queue via `boto3.resource('sqs').Queue(...).send_message`, with the channel resolved from `settings.CAMPAIGN_MESSAGE_SQS` [mercury_api/campaigns/processor/user_messaging.py:469-469].

## Consumer (sqs:la-prod-campaign-messages)
- Zappa event-source binding maps the queue to handler `mercury_campaign_messages.email_sender.process_campaign_message_delivery` on stage `prod`, with ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` [mercury_campaign_messages/zappa_settings.json:73-73].

## Edge evidence
- Producer side: deterministic static AST match on the boto3 send_message call resolved to `la-prod-campaign-messages` (also `la-staging-campaign-messages`, `la-dev-campaign-messages` for other envs) [mercury_api/campaigns/processor/user_messaging.py:469-469].
- Consumer side: authoritative Zappa `event_source` config (stage=prod) wires the SQS ARN to the handler function [mercury_campaign_messages/zappa_settings.json:73-73].

Net edge: `mercury_api` → `sqs:la-prod-campaign-messages` → `mercury_campaign_messages` (Lambda handler `process_campaign_message_delivery`).

### Caveats

- Producer resolution comes from settings literals across multiple env modules (azure_prod/staging, dev, prod, shopagain_prod, staging); only the prod value is `la-prod-campaign-messages`.
- Only one producer call site was found in the packet; other producers may exist but are not in evidence.

### Unknown Because Missing Evidence

- Whether any other services/functions also publish to la-prod-campaign-messages (not present in packet).
- DLQ, visibility timeout, batch size, or IAM policy details for the queue (not in packet).

### Score Notes

Provides producer call site, Zappa-bound consumer handler, queue ARN/name, and lists explicit unknowns, matching the expected answer shape with citations.
