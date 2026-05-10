# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/latticeai_23_eval_2026_05_10`
- Model: `opus`
- Scenario count: 6

## Summary

| Scenario | Score | Failure Modes | Notes |
|---|---|---|---|
| Q082 | Pass | none | Answer enumerates all client env/baseURL references with file/line citations and provides the Apache vhost → WSGI mapping identifying mercury_api/prod_shopagain_wsgi.py as the deployed backend, matching the expected shape. |
| Q083 | Pass | none | Answer enumerates backend token + auth routes and the affected web/mobile callers with explicit repo/path/line citations, matching the expected shape. |
| Q088 | Partial | missing KG fact | The packet conclusively answers the delivery-queue half (queue name, ARN, consumer handler, Zappa citation) but lacks evidence for the scheduling queue and the producer/consumer link between the two, so the 'connect scheduling to delivery' part of the question is unsupported. |
| Q095 | Pass | none | Answer provides the domain-to-WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), enumerates client baseURLs pointing to the domain across repos, and identifies mercury_api as the backend repo, all with line-level citations. |
| Q100 | Pass | none | Answer follows the expected inventory-with-drift shape: lists documented endpoints that lack an exact backend match (only `/v1/collections` via fuzzy match to `/v1/product_collections`) and the documented endpoints flagged right_only in the clients_vs_docs reconciliation, with citations to repo/path/line coordinates and explicit caveats about packet scope. |
| Q106 | Partial | missing KG fact | Consumer, queue ARN, and Zappa handler are clearly evidenced with citations, but the expected shape also requires producer config/send-site candidates, which are absent from the packet. |

## Q082 - Pass

**Question:** Which clients call api.shopagain.io, and which deployed backend serves that domain?

### Answer

## Clients / services that reference `api.shopagain.io`

**Frontend / mobile clients (baseURLs in env):**
- `mercury_ui` – `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1-1], plus hard-coded references in `public/shopagain_script.min.js` [mercury_ui/public/shopagain_script.min.js:L1-1], `public/shopify/shopagain_script.js` [mercury_ui/public/shopify/shopagain_script.js:L32-32], `public/shopify/shopagain_script.min.js` [mercury_ui/public/shopify/shopagain_script.min.js:L1-1], and `public/shopify/widgets.js` [mercury_ui/public/shopify/widgets.js:L31-31].
- `ShopAgainMobile` – `VITE_API_ROOT=https://api.shopagain.io` in both [ShopAgainMobile/.env.development:L1-1] and [ShopAgainMobile/.env.production:L1-1].

**Backend / worker services (config consumers):**
- `mercury_api` itself – `API_URL`, `SMS_WEBHOOK_URL`, `CSRF_COOKIE_DOMAIN`, `SESSION_COOKIE_DOMAIN` all bind to `api.shopagain.io` [mercury_api/mercury_api/settings/shopagain_prod.py:L2-2], [mercury_api/mercury_api/settings/shopagain_prod.py:L4-4], [mercury_api/mercury_api/settings/shopagain_prod.py:L48-48], [mercury_api/mercury_api/settings/shopagain_prod.py:L49-49].
- `mercury_campaign_messages` – `api_url` in [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8-8].
- `mercury_tracking` – `api_url` in [mercury_tracking/common/configmanager/prod.ini:L8-8].
- `mercury_webhooks` – `api_url` in [mercury_webhooks/common/configmanager/prod.ini:L28-28].

**API documentation:**
- `shopagain_api_docs` – server URL referenced in [shopagain_api_docs/dist.json:L14-14], [shopagain_api_docs/dist.json:L60-60], [shopagain_api_docs/docs/dist.json:L18-18], and [shopagain_api_docs/openapi/openapi.yaml:L45-45].

## Deployed backend serving `api.shopagain.io`

The Apache vhost in `ansible-playbooks` routes the domain to a WSGI entrypoint in the `mercury_api` repo:
- Domain → WSGI: `api.shopagain.io` → `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-7].
- Vhost ServerName reference [ansible-playbooks/apache/prod_shopagain.conf:L7-7].

**Backend repo:** `mercury_api` (WSGI entrypoint `mercury_api/prod_shopagain_wsgi.py`).

### Caveats

- `mercury_api` appears as both a caller (its own settings reference the domain for CSRF/session/webhook URLs) and as the served backend.
- Some `mercury_ui` references are in built/minified script bundles, not source modules.

### Unknown Because Missing Evidence

- None.

### Score Notes

Answer enumerates all client env/baseURL references with file/line citations and provides the Apache vhost → WSGI mapping identifying mercury_api/prod_shopagain_wsgi.py as the deployed backend, matching the expected shape.

## Q083 - Pass

**Question:** If token auth endpoints change in the backend, which web and mobile callers are affected?

### Answer

## Backend token/auth routes (mercury-api)

JWT token routes:
- `ANY /api/token/` [mercury_api/companies/urls.py:L63-63]
- `ANY /api/token/refresh/` [mercury_api/companies/urls.py:L64-64]

Broader auth routes that web callers depend on:
- `ANY /auth/login/` [mercury_api/backoffice/urls.py:L17-17]
- `ANY /auth/` [mercury_api/companies/urls.py:L60-60], [mercury_api/woocommerce_app/urls.py:L6-6]
- `ANY /auth/registration/` [mercury_api/companies/urls.py:L61-62]
- `ANY /auth/password/reset/confirm/` [mercury_api/companies/urls.py:L55-55]
- `ANY /auth/account-confirm-email/` [mercury_api/companies/urls.py:L66-66]
- `ANY /auth_internal/` [mercury_api/woocommerce_app/urls.py:L7-7]
- `ANY /reauthenticate/<str:company_id>/` [mercury_api/woocommerce_app/urls.py:L11-11]
- `ANY /reauthenticate_callback/` [mercury_api/woocommerce_app/urls.py:L16-16]

## Mobile callers (shop-again-mobile) — directly affected by JWT token route changes

- `POST /api/token/` [ShopAgainMobile/src/api/login.api.tsx:L6-6]
- `POST /api/token/refresh/` [ShopAgainMobile/src/api/axiosConfig.tsx:L37-37]

No other mobile auth callers appear in the packet. The packet shows no mercury-ui calls to `/api/token/*`, so the web app is not directly affected by JWT token endpoint shape changes per this evidence.

## Web callers (mercury-ui) — affected if broader `/auth/*` routes change

- `POST /auth/logout/` [mercury_ui/src/services/auth.js:L14-14]
- `PATCH /auth/user/` [mercury_ui/src/services/auth.js:L23-23]
- `POST /auth/registration/` [mercury_ui/src/services/auth.js:L27-27]
- `POST /auth/registration/resend-email/` [mercury_ui/src/services/auth.js:L34-34]
- `POST /auth/account-confirm-email/` [mercury_ui/src/services/auth.js:L39-39]
- `POST /auth/password/reset/confirm/` [mercury_ui/src/services/auth.js:L45-45]
- `POST /auth/password/reset/` [mercury_ui/src/services/auth.js:L50-50]
- `POST /auth/password/change/` [mercury_ui/src/services/auth.js:L56-56]
- `GET /get_ggl_auth_login_status/` [mercury_ui/src/services/integration.js:L37-37]
- `POST /add_or_update_ggl_auth_integration/` [mercury_ui/src/services/integration.js:L40-40]
- `POST /remove_ggl_auth_integration/` [mercury_ui/src/services/integration.js:L43-43]
- `GET /get_judge_me_auth_login_status/` [mercury_ui/src/services/integration.js:L68-68]
- `POST /remove_judge_me_auth_integration/` [mercury_ui/src/services/integration.js:L71-71]

## Blast radius summary
- Changes to `/api/token/*` ⇒ break **shop-again-mobile** (login + axios refresh interceptor).
- Changes to `/auth/*` ⇒ break **mercury-ui** auth/registration/password flows; mobile is not shown calling `/auth/*` in this packet.

### Caveats

- Packet only includes deterministic static call/expose facts; runtime/dynamic calls or rewrites by gateways aren't captured.
- No mercury-ui callers to `/api/token/*` were retrieved; absence in packet does not prove absence in code, only in evidence.

### Unknown Because Missing Evidence

- Whether shop-again-mobile or mercury-ui call any of the broader `/reauthenticate*`, `/auth_internal/`, or `/auth/login/` backend routes (no client_call facts in packet).
- Whether `/auth/logout/` and other mercury-ui `/auth/*` calls map to the mercury-api `/auth/` include (likely via dj-rest-auth) — not explicitly evidenced.

### Score Notes

Answer enumerates backend token + auth routes and the affected web/mobile callers with explicit repo/path/line citations, matching the expected shape.

## Q088 - Partial

**Question:** Which SQS queues connect campaign scheduling to message delivery, and who consumes each queue?

### Answer

## Campaign message delivery queue
- **Queue:** `sqs:la-prod-campaign-messages` (ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages`)
- **Consumer:** `mercury-campaign-messages` repo, handler `mercury_campaign_messages.email_sender.process_campaign_message_delivery`, wired as a Zappa `prod` event source [mercury_campaign_messages/zappa_settings.json:L73-L73].

## Campaign scheduling queue
No evidence item was returned for a `la-prod-campaign` (scheduling) queue or its consumer in this packet, so the upstream half of the scheduling→delivery hand-off cannot be confirmed from the provided evidence.

### Caveats

- Only one queue/consumer pair is supported by the packet; the scheduling-side queue is not evidenced even though a retrieval step targeted `la-prod-campaign`.

### Unknown Because Missing Evidence

- Identity of the campaign scheduling queue (e.g., `la-prod-campaign`) and its consumer/producer relationships are not in the evidence items.

### Score Notes

The packet conclusively answers the delivery-queue half (queue name, ARN, consumer handler, Zappa citation) but lacks evidence for the scheduling queue and the producer/consumer link between the two, so the 'connect scheduling to delivery' part of the question is unsupported.

## Q095 - Pass

**Question:** If prod_shopagain_wsgi.py deployment changes, which public domains and clients are impacted?

### Answer

## Impacted public domain
- **api.shopagain.io** is the only public domain routed to `prod_shopagain_wsgi.py`. The Apache vhost maps it to `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-7].

## Backend repo serving the domain
- **mercury_api** is the WSGI target's owning repo. It also self-references the domain in production settings:
  - `API_URL = https://api.shopagain.io/` [mercury_api/mercury_api/settings/shopagain_prod.py:L2]
  - `SMS_WEBHOOK_URL = https://api.shopagain.io/` [mercury_api/mercury_api/settings/shopagain_prod.py:L4]
  - `CSRF_COOKIE_DOMAIN = api.shopagain.io` [mercury_api/mercury_api/settings/shopagain_prod.py:L48]
  - `SESSION_COOKIE_DOMAIN = api.shopagain.io` [mercury_api/mercury_api/settings/shopagain_prod.py:L49]

## Clients/configs that call api.shopagain.io (impacted by any breaking change)
- **ShopAgainMobile** (shop-again-mobile): `VITE_API_ROOT=https://api.shopagain.io` [ShopAgainMobile/.env.development:L1] and [ShopAgainMobile/.env.production:L1].
- **mercury_ui**: `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1]; embedded scripts/widgets call the domain directly:
  - [mercury_ui/public/shopagain_script.min.js:L1]
  - [mercury_ui/public/shopify/shopagain_script.js:L32]
  - [mercury_ui/public/shopify/shopagain_script.min.js:L1]
  - [mercury_ui/public/shopify/widgets.js:L31]
- **mercury_campaign_messages**: `api_url=https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8].
- **mercury_tracking**: `api_url=https://api.shopagain.io` [mercury_tracking/common/configmanager/prod.ini:L8].
- **mercury_webhooks**: `api_url=https://api.shopagain.io` [mercury_webhooks/common/configmanager/prod.ini:L28].
- **shopagain_api_docs** (acme-api): documents the same base URL
  - [shopagain_api_docs/dist.json:L14], [shopagain_api_docs/dist.json:L60]
  - [shopagain_api_docs/docs/dist.json:L18]
  - [shopagain_api_docs/openapi/openapi.yaml:L45]

## Summary
A change to `prod_shopagain_wsgi.py` affects everything served at **api.shopagain.io**, which is consumed by ShopAgainMobile, mercury_ui (web app + Shopify scripts/widgets), mercury_campaign_messages, mercury_tracking, mercury_webhooks, and is documented in shopagain_api_docs. mercury_api itself owns the WSGI and the cookie/session domain bindings.

### Caveats

- Evidence is from static config only (env files, ini, vhost, openapi). Runtime overrides (e.g., env var injection at deploy time) are not visible in this packet.
- Only one Apache vhost mapping was returned; if other vhosts also point to the same WSGI in non-prod, they are not represented here.

### Unknown Because Missing Evidence

- Whether any non-listed services or third-party integrations call api.shopagain.io.
- Specific endpoints/paths in prod_shopagain_wsgi.py that each client depends on.

### Score Notes

Answer provides the domain-to-WSGI mapping (api.shopagain.io → prod_shopagain_wsgi.py), enumerates client baseURLs pointing to the domain across repos, and identifies mercury_api as the backend repo, all with line-level citations.

## Q100 - Pass

**Question:** Which documented ShopAgain API endpoints are not obviously implemented or called by any client?

### Answer

## Documented endpoints with drift signals

### Not obviously implemented (no exact backend match)
- **`/v1/collections`** — only a *possible match* (similarity 0.789) against backend `/v1/product_collections`; documented in `[shopagain_api_docs/dist.json:L403-L404]` and `[shopagain_api_docs/openapi/openapi.yaml:L76-L76]`, while the backend exposes `/v1/product_collections` at `[mercury_api/mercury_api/urls.py:L53-L53]`. Treat as drift unless docs/backend agree on the slug.

All other documented v1 endpoints have an exact `EXPOSES_ENDPOINT` match in `mercury_api/urls.py` or `mercury_webhooks/app.py`: `/v1/company` `[mercury_api/mercury_api/urls.py:L51-L51]`, `/v1/contacts` `[:L50-L50]`, `/v1/products` `[:L52-L52]`, `/v1/carts` `[:L55-L55]`, `/v1/checkouts` `[:L56-L56]`, `/v1/orders` `[:L54-L54]`, `/v1/store_data` `[mercury_webhooks/app.py:L101-L101]`.

### Not obviously called by any scoped client
In the `clients_vs_docs_v1_endpoints` reconciliation (clients = `mercury_ui`, `ShopAgainMobile`, `shopagain-chat-widget`), every documented v1 surface appears as `right_only` (i.e., no matching `CALLS_ENDPOINT` in the packet):
- `ANY/POST /v1/company` `[shopagain_api_docs/dist.json:L90-L91]`, `[shopagain_api_docs/docs/dist.json:L27-L28]`, `[shopagain_api_docs/openapi/openapi.yaml:L67-L67]`
- `ANY/POST /v1/contacts` `[shopagain_api_docs/dist.json:L181-L182]`, `[shopagain_api_docs/openapi/openapi.yaml:L70-L70]`
- `ANY/POST /v1/products` `[shopagain_api_docs/dist.json:L275-L276]`, `[shopagain_api_docs/openapi/openapi.yaml:L73-L73]`
- `ANY/POST /v1/collections` `[shopagain_api_docs/dist.json:L403-L404]`, `[shopagain_api_docs/openapi/openapi.yaml:L76-L76]`
- `ANY/POST /v1/carts` `[shopagain_api_docs/dist.json:L489-L490]`, `[shopagain_api_docs/openapi/openapi.yaml:L79-L79]`
- `ANY/POST /v1/checkouts` `[shopagain_api_docs/dist.json:L581-L582]`, `[shopagain_api_docs/openapi/openapi.yaml:L82-L82]`
- `ANY/POST /v1/orders` `[shopagain_api_docs/dist.json:L713-L714]`, `[shopagain_api_docs/openapi/openapi.yaml:L85-L85]`
- `ANY/POST /v1/store_data` `[shopagain_api_docs/dist.json:L845-L846]`, `[shopagain_api_docs/openapi/openapi.yaml:L88-L88]`

### Net takeaway
- **Implementation drift:** only `/v1/collections` vs. backend `/v1/product_collections` is suspicious.
- **Client-call drift:** the packet contains zero `matched` rows for `clients_vs_docs_v1_endpoints`, so on the evidence shown, no documented v1 endpoint has a confirmed client caller across the three scoped client repos.

### Caveats

- `/v1/collections` vs `/v1/product_collections` may be the same logical surface; rename or alias resolution would clear the drift.
- The clients_vs_docs step shows only right_only rows in the packet (no matched rows). This could reflect packet filtering rather than a complete absence of client calls, so treat 'no client caller' as 'no evidence of caller in the packet'.
- Reconciliation only covers the scoped clients (`mercury_ui`, `ShopAgainMobile`, `shopagain-chat-widget`); other consumers are out of scope.

### Unknown Because Missing Evidence

- Whether `/v1/collections` is intentionally renamed to `/v1/product_collections` (no alias/redirect fact in packet).
- Whether any matched client→docs rows exist outside this packet for the listed endpoints.

### Score Notes

Answer follows the expected inventory-with-drift shape: lists documented endpoints that lack an exact backend match (only `/v1/collections` via fuzzy match to `/v1/product_collections`) and the documented endpoints flagged right_only in the clients_vs_docs reconciliation, with citations to repo/path/line coordinates and explicit caveats about packet scope.

## Q106 - Partial

**Question:** For la-prod-campaign-messages, who produces messages, who consumes them, and what evidence proves the edge?

### Answer

## Queue
- **Channel:** `la-prod-campaign-messages` (SQS)
- **ARN:** `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` [mercury_campaign_messages/zappa_settings.json:L73-L73]

## Consumer (proven)
- **Repo:** `mercury_campaign_messages`
- **Handler:** `mercury_campaign_messages.email_sender.process_campaign_message_delivery`
- **Binding:** Zappa `event_source` for stage `prod` wires the SQS ARN above to the handler — this is an authoritative static config edge (`CONSUMES_EVENT`) [mercury_campaign_messages/zappa_settings.json:L73-L73].

## Producer (not proven by packet)
The packet contains no `PRODUCES_EVENT` / send-site fact for `la-prod-campaign-messages`. The only ancillary fact is that `mercury_api` depends on the `hipo-drf-exceptions` package [hipo-drf-exceptions/pyproject.toml:L1-L1], which does not establish a producer relationship to this queue.

### Caveats

- Consumer edge is authoritative_static (Zappa event_source), so the consumer side is high-confidence.
- The mercury_api → hipo-drf-exceptions dependency is unrelated to SQS production and should not be read as a producer signal.

### Unknown Because Missing Evidence

- Identity of the producer service(s) sending to la-prod-campaign-messages.
- Specific send-site code path / SQS SendMessage call evidence.
- Whether non-prod stages have additional consumers.

### Score Notes

Consumer, queue ARN, and Zappa handler are clearly evidenced with citations, but the expected shape also requires producer config/send-site candidates, which are absent from the packet.
