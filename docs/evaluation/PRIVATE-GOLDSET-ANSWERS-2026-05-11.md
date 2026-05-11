# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/private_goldset_eval_2026_05_11`
- Model: `opus`
- Scenario count: 6

## Summary

| Scenario | Score | Failure Modes | Notes |
|---|---|---|---|
| Q082 | Pass | none | Answer enumerates client env/baseURL references across repos and provides the Apache → WSGI deploy mapping to mercury_api with citations, matching the expected shape. |
| Q083 | Partial | missing KG fact | Backend token/auth routes are well-cited and one mobile caller is identified with file/line. However, the expected shape includes web callers, and the packet contains no web caller evidence. |
| Q088 | Pass | none | All four channels are organized by producer and consumer with file/line citations, Zappa event source is cited, ini config references are included, and the downstream email-activity edge is incorporated into the lineage narrative. |
| Q095 | Pass | none | Answer covers all three expected shape elements: the domain→WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), the backend repo (mercury_api) bound to the domain, and the full list of client baseURLs/configs pointing at api.shopagain.io, each with file/line citations from the packet. |
| Q100 | Pass | none | Answer is organized by reconciliation outcome (matched, possible/fuzzy, right-only) before caveats, lists the documented endpoints lacking obvious callers and the one documented endpoint without a clean backend implementation, and explicitly calls out `/v1/store_data` as repo/service placement drift even though grouped as matched. Citations use repo/path:line coordinates from the packet. |
| Q106 | Pass | none | Answer identifies the producer send-site with file/line, the Zappa-bound consumer handler with queue ARN, cites both edge-proof facts, and includes the downstream `la-prod-email` lineage produced by the consumer as required for event lineage completeness. |

## Q082 - Pass

**Question:** Which clients call api.shopagain.io, and which deployed backend serves that domain?

### Answer

## Clients calling `api.shopagain.io`

- **ShopAgainMobile** — `VITE_API_ROOT=https://api.shopagain.io` declared in `[ShopAgainMobile/.env.development:L1-L1]` and `[ShopAgainMobile/.env.production:L1-L1]`, consumed by the axios client at `[ShopAgainMobile/src/api/axiosConfig.tsx:L8-L8]` and `[ShopAgainMobile/src/api/axiosConfig.tsx:L37-L37]`.
- **mercury-ui** — `REACT_APP_API_ROOT=https://api.shopagain.io/` set in `[mercury_ui/.env.production:L1-L1]`, with code accesses across services and views, e.g. `[mercury_ui/src/services/api.js:L10-L10]`, `[mercury_ui/src/services/engagement.ts:L36-L36]`, `[mercury_ui/src/views/main/Settings.js:L159-L159]`, `[mercury_ui/src/views/main/Widgets/InstallWidgets.tsx:L99-L99]`, `[mercury_ui/src/views/main/WoocommerceSettings.tsx:L24-L24]`, `[mercury_ui/src/views/other/Woocommerce.tsx:L5-L5]`, plus Billing/Getting Started/EmailBuilder/Grapesjs components (`AddCreditsDialog.tsx:L66`, `AddOns.tsx:L39,L64`, `ChangePlanDialog.tsx:L65`, `CustomPlan.tsx:L26`, `PlansAndBenifits.tsx:L333`, `EmailEditor.js:L37`, `Grapesjs/index.tsx:L76`, `ConnectShopify/index.tsx:L22-L23`, `SelectPlan.tsx:L74`, `AddShopifyDialog.js:L48`). Embedded storefront scripts also hardcode the domain: `[mercury_ui/public/shopagain_script.min.js:L1-L1]`, `[mercury_ui/public/shopify/shopagain_script.js:L32-L32]`, `[mercury_ui/public/shopify/shopagain_script.min.js:L1-L1]`, `[mercury_ui/public/shopify/widgets.js:L31-L31]`.
- **mercury-campaign-messages** — `api_url=https://api.shopagain.io` at `[mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8-L8]`.
- **mercury-tracking** — `api_url=https://api.shopagain.io` at `[mercury_tracking/common/configmanager/prod.ini:L8-L8]`.
- **mercury-webhooks** — `api_url=https://api.shopagain.io` at `[mercury_webhooks/common/configmanager/prod.ini:L28-L28]`.
- **shopagain_api_docs** (OpenAPI/docs site) — references the host at `[shopagain_api_docs/dist.json:L14-L14]`, `[shopagain_api_docs/dist.json:L60-L60]`, `[shopagain_api_docs/docs/dist.json:L18-L18]`, and `[shopagain_api_docs/openapi/openapi.yaml:L45-L45]`.

## Backend serving the domain

Apache vhost for `api.shopagain.io` routes to a WSGI entrypoint in **mercury_api**:

- `[ansible-playbooks/apache/prod_shopagain.conf:L2-L7]` maps `api.shopagain.io` → `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` (target repo: `mercury_api`).

The `mercury_api` prod settings self-reference the same domain (server-side `API_URL`, `SMS_WEBHOOK_URL`, and cookie scoping), confirming it is the backend service:

- `API_URL=https://api.shopagain.io/` `[mercury_api/mercury_api/settings/shopagain_prod.py:L2-L2]`
- `SMS_WEBHOOK_URL=https://api.shopagain.io/` `[mercury_api/mercury_api/settings/shopagain_prod.py:L4-L4]`
- `CSRF_COOKIE_DOMAIN=api.shopagain.io` `[mercury_api/mercury_api/settings/shopagain_prod.py:L48-L48]`
- `SESSION_COOKIE_DOMAIN=api.shopagain.io` `[mercury_api/mercury_api/settings/shopagain_prod.py:L49-L49]`

**Summary:** ShopAgainMobile, mercury-ui (and its embedded Shopify scripts), mercury-campaign-messages, mercury-tracking, mercury-webhooks, and the shopagain_api_docs site all target `api.shopagain.io`, which the Apache vhost in ansible-playbooks deploys onto the `mercury_api` Django app via `prod_shopagain_wsgi.py`.

### Caveats

- Some mercury-ui references are in compiled/minified storefront JS, so callers there are static literals rather than env-driven.
- Repo path prefixes shown in citations follow the packet's reported paths; actual on-disk roots may differ.

### Unknown Because Missing Evidence

- No evidence in the packet about which host/server (IP, instance, ansible inventory group) actually runs the Apache vhost.
- No TLS/cert or load-balancer evidence is included.

### Score Notes

Answer enumerates client env/baseURL references across repos and provides the Apache → WSGI deploy mapping to mercury_api with citations, matching the expected shape.

## Q083 - Partial

**Question:** If token auth endpoints change in the backend, which web and mobile callers are affected?

### Answer

## Backend token/auth routes (mercury-api)

JWT token routes:
- `ANY /api/token/` [mercury_api/companies/urls.py:L63-63]
- `ANY /api/token/refresh/` [mercury_api/companies/urls.py:L64-64]

Broader auth routes (would also be impacted if `auth/*` contracts change):
- `ANY /auth/login/` [mercury_api/backoffice/urls.py:L17-17]
- `ANY /auth/` [mercury_api/companies/urls.py:L60-60], [mercury_api/woocommerce_app/urls.py:L6-6]
- `ANY /auth/registration/` [mercury_api/companies/urls.py:L61-61], [mercury_api/companies/urls.py:L62-62]
- `ANY /auth/password/reset/confirm/` [mercury_api/companies/urls.py:L55-55]
- `ANY /auth/account-confirm-email/` [mercury_api/companies/urls.py:L66-66]
- `ANY /auth_internal/` [mercury_api/woocommerce_app/urls.py:L7-7]
- `ANY /reauthenticate/<str:company_id>/` [mercury_api/woocommerce_app/urls.py:L11-11]
- `ANY /reauthenticate_callback/` [mercury_api/woocommerce_app/urls.py:L16-16]

## Affected callers

**Mobile (ShopAgainMobile):**
- `POST ${VITE_API_ROOT}/api/token/refresh/` — token refresh call from the axios client [ShopAgainMobile/src/api/axiosConfig.tsx:L37-37]. Any change to `/api/token/refresh/` (method, payload, response shape) will break mobile session refresh.

**Web:** No web caller facts are present in the packet. See unknowns.

## Bottom line
- Confirmed blast radius for `/api/token/refresh/` changes: ShopAgainMobile axios client [ShopAgainMobile/src/api/axiosConfig.tsx:L37-37].
- `/api/token/` and the various `/auth/*` routes are exposed but have no caller edges in this packet.

### Caveats

- Only one mobile caller edge (token refresh) is in the packet; other token/auth routes have no caller facts here.
- Host for the mobile call is unresolved (`${env:VITE_API_ROOT}`); path match to mercury-api is by route only.

### Unknown Because Missing Evidence

- Whether any web frontend repo calls /api/token/ or /auth/* — no web caller evidence present.
- Callers of /api/token/ (non-refresh), /auth/login/, /auth/registration/, /auth/password/reset/confirm/, /auth/account-confirm-email/, /auth_internal/, /reauthenticate/*.

### Score Notes

Backend token/auth routes are well-cited and one mobile caller is identified with file/line. However, the expected shape includes web callers, and the packet contains no web caller evidence.

## Q088 - Pass

**Question:** Which SQS queues connect campaign scheduling to message delivery, and who consumes each queue?

### Answer

The lineage from campaign scheduling to message delivery flows across four SQS channels:

### 1. `sqs:la-prod-campaign` — campaign scheduling queue
- **Producer:** `campaigns.processor.campaign_event.send_event_to_campaign_queue` via `boto3 ... send_message` resolved from `settings.CAMPAIGN_SQS` [mercury_api/campaigns/processor/campaign_event.py:L58-58].
- **Consumer:** `campaigns.processor.campaign_event_processor.consume_campaign_queue` via `receive_messages` [mercury_api/campaigns/processor/campaign_event_processor.py:L25-25].

### 2. `sqs:la-prod-campaign-messages` — campaign → message-delivery handoff
- **Producer:** `campaigns.processor.user_messaging.send_email_to_queue` (resolved from `settings.CAMPAIGN_MESSAGE_SQS`) [mercury_api/campaigns/processor/user_messaging.py:L469-469].
- **Consumer:** Zappa event source binds the queue ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` to `mercury_campaign_messages.email_sender.process_campaign_message_delivery` [mercury_campaign_messages/zappa_settings.json:L73-73].

### 3. `sqs:la-prod-email` — delivery status / email send queue
- **Producer (downstream of #2):** `mercury_campaign_messages.email_sender.process_campaign_message_delivery` writes here via `config.queueConfig.EMAIL_QUEUE` [mercury_campaign_messages/email_sender.py:L71-71], with the channel pinned in [mercury_campaign_messages/configmanager/prod.ini:L5-5].
- **Consumer:** `campaigns.processor.email_queue_processor.consume_email_queue` [mercury_api/campaigns/processor/email_queue_processor.py:L24-24].

### 4. `sqs:la-prod-email-activity` — delivery-status fan-out (downstream of the email send path)
- **Producers:** `views.ElasticEmail.ElasticEmailView.get` [mercury_webhooks/views/ElasticEmail.py:L56-56] and `views.EmailActivity.EmailActivityView.post` [mercury_webhooks/views/EmailActivity.py:L67-67], both resolving `config.queueConfig.EMAIL_ACTIVITY_QUEUE` from [mercury_webhooks/common/configmanager/prod.ini:L19-19].
- **Consumer:** `stores.event_processor.email_activity_processor.consume_email_activity_queue` [mercury_api/stores/event_processor/email_activity_processor.py:L234-234].

### End-to-end chain
`la-prod-campaign` → (mercury_api scheduler) → `la-prod-campaign-messages` → (Zappa-triggered `process_campaign_message_delivery`) → `la-prod-email` → (mercury_api `consume_email_queue`); webhook callbacks then publish to `la-prod-email-activity`, consumed by mercury_api's email activity processor.

### Caveats

- Channel values resolve to staging/dev variants (la-staging-*, la-dev-*) per the same settings/ini sources; only prod is shown above.
- `la-prod-email-activity` is a downstream fan-out from webhook ingestion, not a direct hop in the scheduling→delivery primary path, but is included as event-lineage impact.

### Unknown Because Missing Evidence

- None.

### Score Notes

All four channels are organized by producer and consumer with file/line citations, Zappa event source is cited, ini config references are included, and the downstream email-activity edge is incorporated into the lineage narrative.

## Q095 - Pass

**Question:** If prod_shopagain_wsgi.py deployment changes, which public domains and clients are impacted?

### Answer

## Impact analysis for `prod_shopagain_wsgi.py`

### Public domain routed to this WSGI
- **`api.shopagain.io`** → `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` via Apache vhost [ansible-playbooks/apache/prod_shopagain.conf:L2-L7].

### Backend repo served by this WSGI
- **mercury_api** (Django) — production settings bind to the same domain:
  - `API_URL = https://api.shopagain.io/` [mercury_api/mercury_api/settings/shopagain_prod.py:L2]
  - `SMS_WEBHOOK_URL = https://api.shopagain.io/` [mercury_api/mercury_api/settings/shopagain_prod.py:L4]
  - `CSRF_COOKIE_DOMAIN = api.shopagain.io` [mercury_api/mercury_api/settings/shopagain_prod.py:L48]
  - `SESSION_COOKIE_DOMAIN = api.shopagain.io` [mercury_api/mercury_api/settings/shopagain_prod.py:L49]

### Clients / services whose base URL points to `api.shopagain.io`
- **ShopAgainMobile** — `VITE_API_ROOT=https://api.shopagain.io` in both [ShopAgainMobile/.env.development:L1] and [ShopAgainMobile/.env.production:L1]; consumed in [ShopAgainMobile/src/api/axiosConfig.tsx:L8] and [ShopAgainMobile/src/api/axiosConfig.tsx:L37].
- **mercury_ui** — `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1]; widely consumed in code, e.g. [mercury_ui/src/services/api.js:L10], [mercury_ui/src/services/engagement.ts:L36], [mercury_ui/src/views/main/Settings.js:L159], [mercury_ui/src/views/main/Widgets/InstallWidgets.tsx:L99], [mercury_ui/src/views/main/WoocommerceSettings.tsx:L24], [mercury_ui/src/views/other/Woocommerce.tsx:L5], [mercury_ui/src/components/other/GettingStarted/Steps/ConnectShopify/index.tsx:L22-L23], [mercury_ui/src/components/other/GettingStarted/Steps/SelectPlan.tsx:L74], [mercury_ui/src/components/viewComponents/Billing/AddCreditsDialog.tsx:L66], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L39], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L64], [mercury_ui/src/components/viewComponents/Billing/ChangePlanDialog.tsx:L65], [mercury_ui/src/components/viewComponents/Billing/CustomPlan.tsx:L26], [mercury_ui/src/components/viewComponents/Billing/PlansAndBenifits.tsx:L333], [mercury_ui/src/components/viewComponents/EmailBuilder/EmailEditor.js:L37], [mercury_ui/src/components/viewComponents/Grapesjs/index.tsx:L76], [mercury_ui/src/components/viewComponents/Settings/AddShopifyDialog.js:L48]. Also hard-coded in storefront scripts: [mercury_ui/public/shopagain_script.min.js:L1], [mercury_ui/public/shopify/shopagain_script.js:L32], [mercury_ui/public/shopify/shopagain_script.min.js:L1], [mercury_ui/public/shopify/widgets.js:L31].
- **mercury_campaign_messages** — `api_url=https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8].
- **mercury_tracking** — `api_url=https://api.shopagain.io` [mercury_tracking/common/configmanager/prod.ini:L8].
- **mercury_webhooks** — `api_url=https://api.shopagain.io` [mercury_webhooks/common/configmanager/prod.ini:L28].
- **shopagain_api_docs** (public API docs) — references `https://api.shopagain.io` in [shopagain_api_docs/dist.json:L14], [shopagain_api_docs/dist.json:L60], [shopagain_api_docs/docs/dist.json:L18], and [shopagain_api_docs/openapi/openapi.yaml:L45].

### Blast radius summary
Any change to `prod_shopagain_wsgi.py` (or the Apache vhost in front of it) directly affects every request to `api.shopagain.io`, which is the single backend endpoint for the **ShopAgainMobile** app, **mercury_ui** web app + Shopify storefront scripts/widgets, the **mercury_campaign_messages**, **mercury_tracking**, and **mercury_webhooks** services, the **mercury_api** server itself (cookies/CSRF/session domain), and the publicly-documented API surface in **shopagain_api_docs**.

### Caveats

- Only the production Apache vhost `prod_shopagain.conf` is shown as routing to `prod_shopagain_wsgi.py`; no other domains are mapped to this WSGI in the packet.
- Storefront scripts under `mercury_ui/public/shopify/*` are embedded on merchant Shopify stores, so downtime propagates to those stores.

### Unknown Because Missing Evidence

- Whether any non-prod or alternate domains (e.g., staging) also route to this same WSGI file — not present in the packet.
- Exact HTTP routes/endpoints served by `prod_shopagain_wsgi.py` are not enumerated.

### Score Notes

Answer covers all three expected shape elements: the domain→WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), the backend repo (mercury_api) bound to the domain, and the full list of client baseURLs/configs pointing at api.shopagain.io, each with file/line citations from the packet.

## Q100 - Pass

**Question:** Which documented ShopAgain API endpoints are not obviously implemented or called by any client?

### Answer

## Documented endpoints that lack an obvious caller
In the `clients_vs_docs_v1_endpoints` reconciliation, **every documented ShopAgain endpoint is `right_only`** — i.e., no scoped client repo (`mercury_ui`, `ShopAgainMobile`, `shopagain-chat-widget`) is observed to call it. The full no-caller set:

- `ANY /v1/company` [shopagain_api_docs/dist.json:L90], `POST /v1/company` [shopagain_api_docs/dist.json:L91] (also at [shopagain_api_docs/docs/dist.json:L27-L28] and [shopagain_api_docs/openapi/openapi.yaml:L67])
- `ANY /v1/contacts` [shopagain_api_docs/dist.json:L181], `POST /v1/contacts` [shopagain_api_docs/dist.json:L182] (also at [shopagain_api_docs/openapi/openapi.yaml:L70])
- `ANY /v1/products` [shopagain_api_docs/dist.json:L275], `POST /v1/products` [shopagain_api_docs/dist.json:L276] (also at [shopagain_api_docs/openapi/openapi.yaml:L73])
- `ANY /v1/collections` [shopagain_api_docs/dist.json:L403], `POST /v1/collections` [shopagain_api_docs/dist.json:L404] (also at [shopagain_api_docs/openapi/openapi.yaml:L76])
- `ANY /v1/carts` [shopagain_api_docs/dist.json:L489], `POST /v1/carts` [shopagain_api_docs/dist.json:L490] (also at [shopagain_api_docs/openapi/openapi.yaml:L79])
- `ANY /v1/checkouts` [shopagain_api_docs/dist.json:L581], `POST /v1/checkouts` [shopagain_api_docs/dist.json:L582] (also at [shopagain_api_docs/openapi/openapi.yaml:L82])
- `ANY /v1/orders` [shopagain_api_docs/dist.json:L713], `POST /v1/orders` [shopagain_api_docs/dist.json:L714] (also at [shopagain_api_docs/openapi/openapi.yaml:L85])
- `ANY /v1/store_data` [shopagain_api_docs/dist.json:L845], `POST /v1/store_data` [shopagain_api_docs/dist.json:L846] (also at [shopagain_api_docs/openapi/openapi.yaml:L88])

## Documented endpoints lacking an obvious backend implementation
From `docs_vs_backend_v1_endpoints`, only one documented path is *not* a clean match to a backend route:

- **Possible/fuzzy match only**: `/v1/collections` (docs) ↔ `/v1/product_collections` (backend), similarity 0.789. Docs: [shopagain_api_docs/dist.json:L403-L404], [shopagain_api_docs/openapi/openapi.yaml:L76]. Backend candidate: [mercury_api/mercury_api/urls.py:L53]. Treat as drift until the names are reconciled.

## Repo/service placement drift to flag (matched, but suspicious)
- `/v1/store_data` is documented under **acme-api** ([shopagain_api_docs/dist.json:L845-L846], [shopagain_api_docs/openapi/openapi.yaml:L88]) but the only implementation in scope is in **mercury_webhooks**, not mercury_api ([mercury_webhooks/app.py:L101]). The reconciler grouped it as `matched`, but the service placement differs from the rest of the acme-api surface.

## Cleanly matched (docs ↔ backend in mercury_api)
Provided only for contrast — these are not in the "missing" set: `/v1/company`, `/v1/contacts`, `/v1/products`, `/v1/carts`, `/v1/checkouts`, `/v1/orders` (e.g., [mercury_api/mercury_api/urls.py:L50-L56]).

## Not part of the answer (right_only backend, undocumented)
Not asked, but noted for completeness: many `mercury_webhooks` routes (mailgun, twilio, sendgrid, whatsapp, plivo, woocommerce, stripe, judgeme, facebook, elementor, gupshup, textlocal, omnibus, razorpay, email_activity, elasticemail, trustsignal) and mercury_api's `/v1/elementor` and `/v1/chatbot` are implemented but undocumented — these are the inverse drift class.

### Caveats

- Every documented endpoint shows as right_only in clients_vs_docs, which most likely means the client repos (mercury_ui, ShopAgainMobile, shopagain-chat-widget) do not directly emit literal `/v1/...` strings the static extractor recognized; absence of CALLS_ENDPOINT evidence is not proof of zero usage.
- `/v1/collections` vs `/v1/product_collections` is only a fuzzy match (similarity 0.789); a human should confirm whether docs or backend has the canonical name.
- `/v1/store_data` is documented under acme-api but implemented in mercury_webhooks — repo/service placement drift even though the reconciler labeled it matched.
- Reconciliation totals reported (matched=30, possible_matches=4, right_only=50) include duplicated rows because the same documented path appears in multiple doc artifacts (dist.json, docs/dist.json, openapi/openapi.yaml) and across both reconciliation steps.

### Unknown Because Missing Evidence

- No `left_only` rows from clients_vs_docs are in the packet, so we cannot list client calls that hit undocumented endpoints.
- The packet does not enumerate the specific CALLS_ENDPOINT facts (or their absence) per client repo, so we cannot distinguish 'no static call extracted' from 'truly uncalled'.

### Score Notes

Answer is organized by reconciliation outcome (matched, possible/fuzzy, right-only) before caveats, lists the documented endpoints lacking obvious callers and the one documented endpoint without a clean backend implementation, and explicitly calls out `/v1/store_data` as repo/service placement drift even though grouped as matched. Citations use repo/path:line coordinates from the packet.

## Q106 - Pass

**Question:** For la-prod-campaign-messages, who produces messages, who consumes them, and what evidence proves the edge?

### Answer

## Channel: sqs:la-prod-campaign-messages

### Producer (send-site)
- `campaigns.processor.user_messaging.send_email_to_queue` invokes `boto3.resource('sqs').Queue(...).send_message` to this queue [mercury_api/campaigns/processor/user_messaging.py:L469-L469]. The channel resolves from `settings.CAMPAIGN_MESSAGE_SQS` (literal `la-prod-campaign-messages` in `mercury_api.settings.*_prod`, with staging/dev variants).

### Consumer (handler)
- The `mercury-campaign-messages` Zappa service is wired to this queue as an event source, dispatching to `mercury_campaign_messages.email_sender.process_campaign_message_delivery` (stage `prod`, ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages`) [mercury_campaign_messages/zappa_settings.json:L73-L73].

### Edge proof
- Producer side: AST-detected `send_message` call with channel literal resolved from settings constant `CAMPAIGN_MESSAGE_SQS` → `la-prod-campaign-messages` [mercury_api/campaigns/processor/user_messaging.py:L469-L469].
- Consumer side: Authoritative static Zappa `event_source` binding mapping the same SQS ARN to `process_campaign_message_delivery` [mercury_campaign_messages/zappa_settings.json:L73-L73].
- Both endpoints share the normalized channel `la-prod-campaign-messages`, closing the producer→consumer edge with one deterministic_static and one authoritative_static fact.

### Downstream lineage (impact)
- The consumer handler `process_campaign_message_delivery` then produces to `sqs:la-prod-email` via `send_message` [mercury_campaign_messages/email_sender.py:L71-L71], resolved from `config.queueConfig.EMAIL_QUEUE` in `mercury_campaign_messages/configmanager/prod.ini` [mercury_campaign_messages/configmanager/prod.ini:L5-L5].
- That downstream `la-prod-email` queue is consumed by `campaigns.processor.email_queue_processor.consume_email_queue` in `mercury_api` [mercury_api/campaigns/processor/email_queue_processor.py:L24-L24]. So the end-to-end chain is: `mercury_api` producer → `la-prod-campaign-messages` → `mercury_campaign_messages` handler → `la-prod-email` → `mercury_api` email queue consumer.

### Caveats

- Channel literals resolve per-stage; prod is `la-prod-campaign-messages`, with `la-staging-campaign-messages` and `la-dev-campaign-messages` for staging/dev.
- Only one producer send-site and one Zappa-bound consumer are present in the packet for this channel; additional callers (if any) are not represented here.

### Unknown Because Missing Evidence

- Message schema/payload contract between producer and `process_campaign_message_delivery` is not in the packet.
- Whether other services besides `mercury-campaign-messages` also subscribe to `la-prod-campaign-messages` is not shown.

### Score Notes

Answer identifies the producer send-site with file/line, the Zappa-bound consumer handler with queue ARN, cites both edge-proof facts, and includes the downstream `la-prod-email` lineage produced by the consumer as required for event lineage completeness.
