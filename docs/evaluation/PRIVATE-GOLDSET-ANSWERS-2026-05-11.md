# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/private_goldset_eval_2026_05_11`
- Model: `opus`
- Scenario count: 6

## Summary

| Scenario | Score | Failure Modes | Notes |
|---|---|---|---|
| Q082 | Pass | none | Answer enumerates all client/service callers from the packet and identifies the Apache→WSGI deploy mapping to mercury_api, matching the expected shape (client env/baseURL refs plus Apache deploy mapping to backend repo and WSGI entrypoint). |
| Q083 | Pass | none | Answer enumerates the backend token routes and the directly affected mobile callers with file/line citations, and explicitly notes the absence of web callers for those token paths, matching the expected shape. |
| Q088 | Pass | none | Answer covers all four queues with producers, consumers (including Zappa event-source binding), and config references as requested; downstream lineage edges (campaign → campaign-messages → email → email-activity) are all included. |
| Q095 | Pass | none | Answer provides the domain→WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), enumerates client baseURL configs pointing to that domain across all repos in the packet, and cites backend repo evidence with file/line coordinates—matching the expected answer shape. |
| Q100 | Pass | none | Answer organizes findings by outcome (exact matches, possible/fuzzy matches, right_only) per the contract reconciliation rubric, identifies /v1/collections as the documented-but-not-obviously-implemented case via fuzzy match, lists all documented endpoints that lack a client caller, calls out mercury_webhooks placement drift for /v1/store_data, and cites coordinates from the packet without inventing facts. |
| Q106 | Pass | none | Packet provides producer send-site, Zappa consumer handler with ARN, and the downstream la-prod-email edge produced by the same consumer; all cited with coordinates and explicit unknowns listed. |

## Q082 - Pass

**Question:** Which clients call api.shopagain.io, and which deployed backend serves that domain?

### Answer

## Backend serving api.shopagain.io

The Apache vhost in ansible-playbooks routes `api.shopagain.io` to the `mercury_api` repo via WSGI entrypoint `/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-7].

## Clients / services that reference api.shopagain.io

**ShopAgainMobile** (Vite app)
- `VITE_API_ROOT=https://api.shopagain.io` in [ShopAgainMobile/.env.development:L1-1] and [ShopAgainMobile/.env.production:L1-1]
- Consumed in [ShopAgainMobile/src/api/axiosConfig.tsx:L8-8] and [ShopAgainMobile/src/api/axiosConfig.tsx:L37-37]

**mercury_ui** (React app)
- `REACT_APP_API_ROOT=https://api.shopagain.io/` in [mercury_ui/.env.production:L1-1]
- Code references include [mercury_ui/src/services/api.js:L10-10], [mercury_ui/src/services/engagement.ts:L36-36], [mercury_ui/src/views/main/Settings.js:L159-159], [mercury_ui/src/views/main/Widgets/InstallWidgets.tsx:L99-99], [mercury_ui/src/views/main/WoocommerceSettings.tsx:L24-24], [mercury_ui/src/views/other/Woocommerce.tsx:L5-5], [mercury_ui/src/components/other/GettingStarted/Steps/ConnectShopify/index.tsx:L22-23], [mercury_ui/src/components/other/GettingStarted/Steps/SelectPlan.tsx:L74-74], [mercury_ui/src/components/viewComponents/Billing/AddCreditsDialog.tsx:L66-66], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L39-39], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L64-64], [mercury_ui/src/components/viewComponents/Billing/ChangePlanDialog.tsx:L65-65], [mercury_ui/src/components/viewComponents/Billing/CustomPlan.tsx:L26-26], [mercury_ui/src/components/viewComponents/Billing/PlansAndBenifits.tsx:L333-333], [mercury_ui/src/components/viewComponents/EmailBuilder/EmailEditor.js:L37-37], [mercury_ui/src/components/viewComponents/Grapesjs/index.tsx:L76-76], [mercury_ui/src/components/viewComponents/Settings/AddShopifyDialog.js:L48-48]
- Embedded Shopify/widget scripts: [mercury_ui/public/shopagain_script.min.js:L1-1], [mercury_ui/public/shopify/shopagain_script.js:L32-32], [mercury_ui/public/shopify/shopagain_script.min.js:L1-1], [mercury_ui/public/shopify/widgets.js:L31-31]

**mercury_api** (self-references in prod settings)
- `API_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L2-2], `SMS_WEBHOOK_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L4-4], `CSRF_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L48-48], `SESSION_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L49-49]

**Backend workers / sibling services** (server-to-server callers)
- `mercury_campaign_messages`: `api_url=https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8-8]
- `mercury_tracking`: `api_url` [mercury_tracking/common/configmanager/prod.ini:L8-8]
- `mercury_webhooks`: `api_url` [mercury_webhooks/common/configmanager/prod.ini:L28-28]

**API docs**
- `shopagain_api_docs` references the domain in [shopagain_api_docs/openapi/openapi.yaml:L45-45], [shopagain_api_docs/dist.json:L14-14], [shopagain_api_docs/dist.json:L60-60], [shopagain_api_docs/docs/dist.json:L18-18]

## Summary
Production API domain `api.shopagain.io` is served by the `mercury_api` Django/WSGI app (entrypoint `prod_shopagain_wsgi.py`). It is consumed by two frontends (`ShopAgainMobile`, `mercury_ui` + its embedded Shopify scripts), three backend services (`mercury_campaign_messages`, `mercury_tracking`, `mercury_webhooks`), and documented in `shopagain_api_docs`.

### Caveats

- mercury_api's references to api.shopagain.io are self-config (cookie domains, callback URLs), not external client calls.
- Some mercury_ui hits are in minified JS bundles that may be build artifacts rather than source.

### Unknown Because Missing Evidence

- None.

### Score Notes

Answer enumerates all client/service callers from the packet and identifies the Apache→WSGI deploy mapping to mercury_api, matching the expected shape (client env/baseURL refs plus Apache deploy mapping to backend repo and WSGI entrypoint).

## Q083 - Pass

**Question:** If token auth endpoints change in the backend, which web and mobile callers are affected?

### Answer

## Backend token endpoints (mercury-api)

- `ANY /api/token/` [mercury_api/companies/urls.py:L63-63]
- `ANY /api/token/refresh/` [mercury_api/companies/urls.py:L64-64]

## Mobile callers affected (ShopAgainMobile)

- `POST /api/token/` — login flow [ShopAgainMobile/src/api/login.api.tsx:L6-6]
- `POST /api/token/refresh/` — axios refresh interceptor [ShopAgainMobile/src/api/axiosConfig.tsx:L37-37]

## Web callers affected (mercury-ui)

No direct `/api/token/` or `/api/token/refresh/` callers are present in the evidence for mercury-ui. The UI's auth surface targets `/auth/*` (e.g., logout, user, registration, password) which would be impacted only if those routes change, not the JWT token routes.

## Impact summary

Changes to `/api/token/` or `/api/token/refresh/` directly break the ShopAgainMobile app (login + token-refresh interceptor). The mercury-ui repo has no observed coupling to these two token routes in the packet.

### Adjacent (non-token) auth surface for context

- Backend auth routes exposed by mercury-api include `/auth/login/` [mercury_api/backoffice/urls.py:L17-17], `/auth/` [mercury_api/companies/urls.py:L60-60], `/auth/registration/` [mercury_api/companies/urls.py:L61-61, L62-62], `/auth/password/reset/confirm/` [mercury_api/companies/urls.py:L55-55], `/auth/account-confirm-email/` [mercury_api/companies/urls.py:L66-66], `/auth/` [mercury_api/woocommerce_app/urls.py:L6-6], `/auth_internal/` [mercury_api/woocommerce_app/urls.py:L7-7], `/reauthenticate/<str:company_id>/` [mercury_api/woocommerce_app/urls.py:L11-11], `/reauthenticate_callback/` [mercury_api/woocommerce_app/urls.py:L16-16].
- mercury-ui auth callers: `/auth/logout/` [mercury_ui/src/services/auth.js:L14-14], `/auth/user/` [mercury_ui/src/services/auth.js:L23-23], `/auth/registration/` [mercury_ui/src/services/auth.js:L27-27], `/auth/registration/resend-email/` [mercury_ui/src/services/auth.js:L34-34], `/auth/account-confirm-email/` [mercury_ui/src/services/auth.js:L39-39], `/auth/password/reset/confirm/` [mercury_ui/src/services/auth.js:L45-45], `/auth/password/reset/` [mercury_ui/src/services/auth.js:L50-50], `/auth/password/change/` [mercury_ui/src/services/auth.js:L56-56].

### Caveats

- Host base URLs are unresolved env vars (VITE_API_ROOT for mobile, REACT_APP_API_ROOT for web); path-only matches are reported.
- Evidence covers static axios/Django path facts only; runtime/dynamic call sites are not represented.

### Unknown Because Missing Evidence

- Whether any mercury-ui module not in src/services/auth.js or integration.js calls /api/token/ or /api/token/refresh/.
- Whether ShopAgainMobile has additional token call sites beyond axiosConfig.tsx and login.api.tsx.

### Score Notes

Answer enumerates the backend token routes and the directly affected mobile callers with file/line citations, and explicitly notes the absence of web callers for those token paths, matching the expected shape.

## Q088 - Pass

**Question:** Which SQS queues connect campaign scheduling to message delivery, and who consumes each queue?

### Answer

## Event lineage: scheduling → delivery → activity

Four SQS channels stitch campaign scheduling to message delivery and downstream activity. Flow: `la-prod-campaign` → `la-prod-campaign-messages` → `la-prod-email` → `la-prod-email-activity`.

### 1. `sqs:la-prod-campaign` (scheduling intake)
- **Producer:** `campaigns.processor.campaign_event.send_event_to_campaign_queue` via `settings.CAMPAIGN_SQS` [mercury_api/campaigns/processor/campaign_event.py:L58-58].
- **Consumer:** `campaigns.processor.campaign_event_processor.consume_campaign_queue` via `CAMPAIGN_SQS` (`receive_messages`) [mercury_api/campaigns/processor/campaign_event_processor.py:L25-25].

### 2. `sqs:la-prod-campaign-messages` (per-recipient fan-out)
- **Producer:** `campaigns.processor.user_messaging.send_email_to_queue` via `settings.CAMPAIGN_MESSAGE_SQS` [mercury_api/campaigns/processor/user_messaging.py:L469-469].
- **Consumer:** `mercury-campaign-messages` Lambda, wired by Zappa event-source ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` to handler `mercury_campaign_messages.email_sender.process_campaign_message_delivery` [mercury_campaign_messages/zappa_settings.json:L73-73].

### 3. `sqs:la-prod-email` (delivery status / send queue)
- **Producer:** `mercury_campaign_messages.email_sender.process_campaign_message_delivery` via `config.queueConfig.EMAIL_QUEUE` [mercury_campaign_messages/email_sender.py:L71-71]; channel sourced from `[queue] email_queue` in [mercury_campaign_messages/configmanager/prod.ini:L5-5].
- **Consumer:** `campaigns.processor.email_queue_processor.consume_email_queue` via `EMAIL_SQS` (`receive_messages`) [mercury_api/campaigns/processor/email_queue_processor.py:L24-24].

### 4. `sqs:la-prod-email-activity` (downstream activity events)
- **Producers (mercury_webhooks):** `views.ElasticEmail.ElasticEmailView.get` [mercury_webhooks/views/ElasticEmail.py:L56-56] and `views.EmailActivity.EmailActivityView.post` [mercury_webhooks/views/EmailActivity.py:L67-67], both via `config.queueConfig.EMAIL_ACTIVITY_QUEUE` defined at [mercury_webhooks/common/configmanager/prod.ini:L19-19].
- **Consumer:** `stores.event_processor.email_activity_processor.consume_email_activity_queue` via `EMAIL_ACTIVITY_SQS` (`receive_messages`) [mercury_api/stores/event_processor/email_activity_processor.py:L234-234].

### Config / settings references
- `CAMPAIGN_SQS`, `CAMPAIGN_MESSAGE_SQS`, `EMAIL_SQS`, `EMAIL_ACTIVITY_SQS` are defined across `mercury_api.settings.{prod,staging,dev,azure_prod,azure_staging,shopagain_prod}` modules (per resolution metadata on each producer/consumer fact).
- `mercury_campaign_messages/configmanager/{dev,prod,staging}.ini` provides `[queue] email_queue`.
- `mercury_webhooks/common/configmanager/{dev,prod,staging}.ini` provides `[queue] email_activity_queue`.

### Caveats

- Channel addresses shown are the prod values; staging/dev resolve to `la-staging-*` / `la-dev-*` from the same settings keys.
- Only the `mercury-campaign-messages` consumer is bound via Zappa event source; the other consumers use direct `receive_messages` polling loops.

### Unknown Because Missing Evidence

- None.

### Score Notes

Answer covers all four queues with producers, consumers (including Zappa event-source binding), and config references as requested; downstream lineage edges (campaign → campaign-messages → email → email-activity) are all included.

## Q095 - Pass

**Question:** If prod_shopagain_wsgi.py deployment changes, which public domains and clients are impacted?

### Answer

## Public domain impacted

- **api.shopagain.io** is the only public domain routed to `prod_shopagain_wsgi.py`. The Apache vhost binds `api.shopagain.io` to `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-L7], confirming the target repo hint `mercury_api`.

## Backend / server-side impact

- **mercury_api** (the WSGI target itself) — production settings hardcode the domain for `API_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L2], `SMS_WEBHOOK_URL` [mercury_api/mercury_api/settings/shopagain_prod.py:L4], `CSRF_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L48], and `SESSION_COOKIE_DOMAIN` [mercury_api/mercury_api/settings/shopagain_prod.py:L49].
- **mercury_campaign_messages** — `api_url=https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8].
- **mercury_tracking** — `api_url=https://api.shopagain.io` [mercury_tracking/common/configmanager/prod.ini:L8].
- **mercury_webhooks** — `api_url=https://api.shopagain.io` [mercury_webhooks/common/configmanager/prod.ini:L28].

## Client / frontend impact

- **mercury_ui** (web app) — production `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1]; consumed in axios/services and many views, e.g. `src/services/api.js` [mercury_ui/src/services/api.js:L10], `src/services/engagement.ts` [mercury_ui/src/services/engagement.ts:L36], `src/views/main/Settings.js` [mercury_ui/src/views/main/Settings.js:L159], `src/views/main/Widgets/InstallWidgets.tsx` [mercury_ui/src/views/main/Widgets/InstallWidgets.tsx:L99], `src/views/main/WoocommerceSettings.tsx` [mercury_ui/src/views/main/WoocommerceSettings.tsx:L24], `src/views/other/Woocommerce.tsx` [mercury_ui/src/views/other/Woocommerce.tsx:L5], `src/components/other/GettingStarted/Steps/ConnectShopify/index.tsx` [mercury_ui/src/components/other/GettingStarted/Steps/ConnectShopify/index.tsx:L22-L23], `src/components/other/GettingStarted/Steps/SelectPlan.tsx` [mercury_ui/src/components/other/GettingStarted/Steps/SelectPlan.tsx:L74], Billing pages [mercury_ui/src/components/viewComponents/Billing/AddCreditsDialog.tsx:L66], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L39], [mercury_ui/src/components/viewComponents/Billing/AddOns.tsx:L64], [mercury_ui/src/components/viewComponents/Billing/ChangePlanDialog.tsx:L65], [mercury_ui/src/components/viewComponents/Billing/CustomPlan.tsx:L26], [mercury_ui/src/components/viewComponents/Billing/PlansAndBenifits.tsx:L333], EmailBuilder [mercury_ui/src/components/viewComponents/EmailBuilder/EmailEditor.js:L37], Grapesjs [mercury_ui/src/components/viewComponents/Grapesjs/index.tsx:L76], Settings/AddShopifyDialog [mercury_ui/src/components/viewComponents/Settings/AddShopifyDialog.js:L48].
- **mercury_ui storefront scripts** — embedded `api.shopagain.io` literal in `public/shopagain_script.min.js` [mercury_ui/public/shopagain_script.min.js:L1], `public/shopify/shopagain_script.js` [mercury_ui/public/shopify/shopagain_script.js:L32], `public/shopify/shopagain_script.min.js` [mercury_ui/public/shopify/shopagain_script.min.js:L1], `public/shopify/widgets.js` [mercury_ui/public/shopify/widgets.js:L31].
- **ShopAgainMobile** — `VITE_API_ROOT=https://api.shopagain.io` in [ShopAgainMobile/.env.development:L1] and [ShopAgainMobile/.env.production:L1]; consumed in axios client [ShopAgainMobile/src/api/axiosConfig.tsx:L8], [ShopAgainMobile/src/api/axiosConfig.tsx:L37].
- **shopagain_api_docs** — OpenAPI/dev portal pin to the domain in [shopagain_api_docs/dist.json:L14], [shopagain_api_docs/dist.json:L60], [shopagain_api_docs/docs/dist.json:L18], and [shopagain_api_docs/openapi/openapi.yaml:L45].

## Bottom line

Any change to `prod_shopagain_wsgi.py` deployment alters the behavior reachable at `api.shopagain.io`, which is depended on by: backend services `mercury_campaign_messages`, `mercury_tracking`, `mercury_webhooks` (server-to-server via `api_url`); the `mercury_ui` web app and its embedded Shopify storefront scripts; the `ShopAgainMobile` app; and the externally-published `shopagain_api_docs` (OpenAPI spec).

### Caveats

- Apache vhost evidence directly ties only `api.shopagain.io` to `prod_shopagain_wsgi.py`; no other domain mapping is present in the packet.
- The mercury_api references are within the WSGI target itself (settings consumed by the same app), not external clients.

### Unknown Because Missing Evidence

- Whether non-prod domains or additional vhosts also map to this WSGI file (not present in packet).
- Runtime traffic volume / criticality per client (not in packet).

### Score Notes

Answer provides the domain→WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), enumerates client baseURL configs pointing to that domain across all repos in the packet, and cites backend repo evidence with file/line coordinates—matching the expected answer shape.

## Q100 - Pass

**Question:** Which documented ShopAgain API endpoints are not obviously implemented or called by any client?

### Answer

## Documented endpoints with no obvious client caller (right_only in clients_vs_docs)
Every v1 endpoint documented in `shopagain_api_docs` appears as `right_only` in the clients-vs-docs reconciliation, i.e. no call from `mercury_ui`, `ShopAgainMobile`, or `shopagain-chat-widget` matches them:
- `ANY /v1/company` [shopagain_api_docs/dist.json:90], `POST /v1/company` [shopagain_api_docs/dist.json:91], plus duplicates in [shopagain_api_docs/docs/dist.json:27-28] and [shopagain_api_docs/openapi/openapi.yaml:67]
- `ANY /v1/contacts` [shopagain_api_docs/dist.json:181], `POST /v1/contacts` [shopagain_api_docs/dist.json:182], also [shopagain_api_docs/openapi/openapi.yaml:70]
- `ANY /v1/products` [shopagain_api_docs/dist.json:275], `POST /v1/products` [shopagain_api_docs/dist.json:276], also [shopagain_api_docs/openapi/openapi.yaml:73]
- `ANY /v1/collections` [shopagain_api_docs/dist.json:403], `POST /v1/collections` [shopagain_api_docs/dist.json:404], also [shopagain_api_docs/openapi/openapi.yaml:76]
- `ANY /v1/carts` [shopagain_api_docs/dist.json:489], `POST /v1/carts` [shopagain_api_docs/dist.json:490], also [shopagain_api_docs/openapi/openapi.yaml:79]
- `ANY /v1/checkouts` [shopagain_api_docs/dist.json:581], `POST /v1/checkouts` [shopagain_api_docs/dist.json:582], also [shopagain_api_docs/openapi/openapi.yaml:82]
- `ANY /v1/orders` [shopagain_api_docs/dist.json:713], `POST /v1/orders` [shopagain_api_docs/dist.json:714], also [shopagain_api_docs/openapi/openapi.yaml:85]
- `ANY /v1/store_data` [shopagain_api_docs/dist.json:845], `POST /v1/store_data` [shopagain_api_docs/dist.json:846], also [shopagain_api_docs/openapi/openapi.yaml:88]

No `matched` rows are present in the `clients_vs_docs_v1_endpoints` step in this packet, so for the scoped clients none of the documented v1 endpoints have a confirmed caller.

## Possible/fuzzy matches against the backend (naming drift)
- `ANY /v1/collections` and `POST /v1/collections` (docs) only fuzzy-match backend `ANY /v1/product_collections` (`similarity=0.789`): [shopagain_api_docs/dist.json:403-404], [shopagain_api_docs/openapi/openapi.yaml:76] vs [mercury_api/mercury_api/urls.py:53]. Treat `/v1/collections` as not obviously implemented under that name.

## Exact matches (documented + implemented in backend)
These documented endpoints do have a backend implementation (so they're only "uncalled", not "unimplemented"):
- `/v1/company` → [mercury_api/mercury_api/urls.py:51]
- `/v1/contacts` → [mercury_api/mercury_api/urls.py:50]
- `/v1/products` → [mercury_api/mercury_api/urls.py:52]
- `/v1/carts` → [mercury_api/mercury_api/urls.py:55]
- `/v1/checkouts` → [mercury_api/mercury_api/urls.py:56]
- `/v1/orders` → [mercury_api/mercury_api/urls.py:54]
- `/v1/store_data` → [mercury_webhooks/app.py:101]

## Repo/service placement note
`/v1/store_data` is documented as part of the ShopAgain public API but is actually implemented in `mercury_webhooks` (Flask) rather than `mercury_api` (Django) — placement drift worth flagging even though it is `matched` [shopagain_api_docs/dist.json:845-846] vs [mercury_webhooks/app.py:101].

## Net answer
- Documented but not obviously implemented under the documented name: **`/v1/collections`** (only a fuzzy match to backend `/v1/product_collections`).
- Documented but with no client caller in scope: **all eight** documented v1 resources (`/v1/company`, `/v1/contacts`, `/v1/products`, `/v1/collections`, `/v1/carts`, `/v1/checkouts`, `/v1/orders`, `/v1/store_data`).

### Caveats

- The clients_vs_docs step shows zero matched rows in the packet; this could mean the scoped clients (mercury_ui, ShopAgainMobile, shopagain-chat-widget) genuinely don't call any documented /v1/ endpoint, or that CALLS_ENDPOINT facts were not extracted for those repos. The right_only count of 50 mixes both reconciliation steps and includes many backend-only routes (e.g., mercury_webhooks integrations like /v1/mailgun, /v1/twilio, /v1/stripe) that aren't documented.
- `/v1/store_data` is documented as a ShopAgain API endpoint but lives in mercury_webhooks rather than mercury_api — service-placement drift even though reconciliation marks it matched.
- Many backend endpoints exist that are not documented at all (e.g., /v1/elementor, /v1/chatbot, /v1/mailgun, /v1/twilio, /v1/sendgrid, /v1/whatsapp/*, /v1/plivo, /v1/woocommerce, /v1/stripe, /v1/judgeme/*, /v1/facebook, /v1/gupshup, /v1/textlocal, /v1/omnibus/*, /v1/razorpay, /v1/email_activity, /v1/elasticemail, /v1/trustsignal); these are the inverse drift and out-of-scope for the asked question but explain the right_only=50 figure.

### Unknown Because Missing Evidence

- Whether any `left_only` documented endpoints exist in docs_vs_backend (the packet contains no explicit left_only rows, so we cannot list documented endpoints with zero backend match other than the fuzzy /v1/collections case).
- Whether the absence of matched rows in clients_vs_docs reflects no extracted CALLS_ENDPOINT facts for the listed client repos versus a true caller gap.
- Sub-paths/methods beyond the top-level resource (e.g., /v1/orders/{id}) — the packet only enumerates resource roots.

### Score Notes

Answer organizes findings by outcome (exact matches, possible/fuzzy matches, right_only) per the contract reconciliation rubric, identifies /v1/collections as the documented-but-not-obviously-implemented case via fuzzy match, lists all documented endpoints that lack a client caller, calls out mercury_webhooks placement drift for /v1/store_data, and cites coordinates from the packet without inventing facts.

## Q106 - Pass

**Question:** For la-prod-campaign-messages, who produces messages, who consumes them, and what evidence proves the edge?

### Answer

## Channel: `sqs:la-prod-campaign-messages`

### Producer (send-site)
- `campaigns.processor.user_messaging.send_email_to_queue` in `mercury_api` calls `boto3.resource('sqs').Queue(...).send_message` targeting `settings.CAMPAIGN_MESSAGE_SQS` which resolves to `la-prod-campaign-messages` (prod) [mercury_api/campaigns/processor/user_messaging.py:L469-L469].
  - Config source: `mercury_api.settings.{azure_prod,prod,shopagain_prod,staging,azure_staging,dev}.CAMPAIGN_MESSAGE_SQS` → `[la-prod-campaign-messages, la-staging-campaign-messages, la-dev-campaign-messages]`.

### Consumer (handler)
- `mercury-campaign-messages` Lambda is wired to consume the queue via Zappa event source: ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages`, stage `prod`, dispatched to `mercury_campaign_messages.email_sender.process_campaign_message_delivery` [mercury_campaign_messages/zappa_settings.json:L73-L73] (authoritative static config).

### Downstream lineage (impact)
The consumer handler then produces onto `sqs:la-prod-email`:
- `mercury_campaign_messages.email_sender.process_campaign_message_delivery` sends via `boto3.resource('sqs').Queue(...).send_message` using `config.queueConfig.EMAIL_QUEUE` → `la-prod-email` [mercury_campaign_messages/email_sender.py:L71-L71].
- Config reference for `email_queue` in the `[queue]` section of `mercury_campaign_messages/configmanager/prod.ini:L5-L5`.
- Downstream `la-prod-email` is then consumed by `campaigns.processor.email_queue_processor.consume_email_queue` [mercury_api/campaigns/processor/email_queue_processor.py:L24-L24].

### Edge evidence summary
| Role | Subject | Fact | Coord |
|---|---|---|---|
| Producer | `send_email_to_queue` | PRODUCES_EVENT sqs:la-prod-campaign-messages | `mercury_api/campaigns/processor/user_messaging.py:L469` |
| Consumer (Zappa) | `process_campaign_message_delivery` | CONSUMES_EVENT sqs:la-prod-campaign-messages | `mercury_campaign_messages/zappa_settings.json:L73` |
| Downstream producer | `process_campaign_message_delivery` | PRODUCES_EVENT sqs:la-prod-email | `mercury_campaign_messages/email_sender.py:L71` |
| Downstream consumer | `consume_email_queue` | CONSUMES_EVENT sqs:la-prod-email | `mercury_api/campaigns/processor/email_queue_processor.py:L24` |

### Caveats

- Queue name resolves per environment from settings; prod value is `la-prod-campaign-messages` (staging/dev variants also exist).
- Consumer binding is authoritative via Zappa event source mapping rather than an in-code `receive_messages` site.

### Unknown Because Missing Evidence

- No evidence in the packet for a DLQ, retry policy, batch size, or message schema for la-prod-campaign-messages.
- No IAM/permission evidence linking producer principal to the queue ARN.

### Score Notes

Packet provides producer send-site, Zappa consumer handler with ARN, and the downstream la-prod-email edge produced by the same consumer; all cited with coordinates and explicit unknowns listed.
