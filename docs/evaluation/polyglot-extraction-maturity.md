# Polyglot Extraction Maturity — .NET & TS/JS

Tracks incremental maturing of .NET (C#) and TypeScript/JavaScript extraction toward
Python parity, measured against a fixed set of linked OSS microservice fixtures.

Each coding pass appends a new **Run** with the same measurements, so we can watch the
gap close run over run. Methodology, fixtures, and the backlog are stable; only the Run
log grows.

> Fixtures and their KG snapshots are intentionally **uncommitted**. Source checkouts live
> outside this repo under the org root `$ORG` (e.g. `../orgs/`); snapshots land in gitignored
> `data/kg_runs/fx_*`.

---

## Fixtures

Linked OSS microservice repos, cloned shallow under the org root `$ORG` (e.g. `../orgs/`, mirrors the
latticeai/mercury org layout). Commit SHAs pin each Run for reproducibility (see per-run
notes if a fixture is re-pulled).

| Org folder | Repo | Lang | Role / linkage signal |
|---|---|---|---|
| `realworld/` | `aspnetcore-realworld` (gothinkster) | .NET | Conduit API controllers (EXPOSES_ENDPOINT) |
| `realworld/` | `nestjs-realworld` (adr1enbe4udou1n) | TS | Conduit API NestJS routes |
| `realworld/` | `react-realworld` (gothinkster) | JS | frontend `superagent` client → Conduit API (CALLS_ENDPOINT) |
| `dotnet/` | `eShop` (Microsoft) | .NET | RabbitMQ integration events + gRPC + minimal APIs |
| `dotnet/` | `run-aspnetcore-microservices` (aspnetrun) | .NET | MassTransit/RabbitMQ Basket→Ordering + gRPC + controllers |
| `typescript/` | `booking-microservices-nestjs` (meysamhadeli) | TS | NestJS + RabbitMQ + axios REST |
| `typescript/` | `microservices-ecommerce` (mmdhossein) | TS | NestJS + KafkaJS producer→consumer |
| `otel/` | `opentelemetry-demo` (open-telemetry) | poly | .NET Kafka consumer + .NET gRPC cart + TS frontend |

The `realworld/` set is the only **cross-repo** fixture (3 repos sharing one HTTP contract);
the rest are monorepos with internal services.

---

## How to run a measurement

Rebuild snapshots (from repo root, `.venv` active):

```bash
ORG=../orgs
python -m source.scripts.build_multi_kg \
  --repo $ORG/realworld/aspnetcore-realworld \
  --repo $ORG/realworld/nestjs-realworld \
  --repo $ORG/realworld/react-realworld \
  --out data/kg_runs/fx_realworld
python -m source.scripts.build_kg --repo $ORG/dotnet/eShop --out data/kg_runs/fx_eshop
python -m source.scripts.build_kg --repo $ORG/dotnet/run-aspnetcore-microservices --out data/kg_runs/fx_run_aspnetcore
python -m source.scripts.build_kg --repo $ORG/typescript/booking-microservices-nestjs --out data/kg_runs/fx_booking_nestjs
python -m source.scripts.build_kg --repo $ORG/typescript/microservices-ecommerce --out data/kg_runs/fx_ts_ecommerce
python -m source.scripts.build_kg --repo $ORG/otel/opentelemetry-demo --out data/kg_runs/fx_otel
```

Measure (the exact breakdown used in every Run below):

```bash
python - <<'PY'
import json, pathlib, collections
SNAPS = {
 "realworld(.NET+TS+JS x-repo)":"fx_realworld",
 "eShop(.NET)":"fx_eshop",
 "run-aspnetcore(.NET)":"fx_run_aspnetcore",
 "booking-nestjs(TS)":"fx_booking_nestjs",
 "ts-ecommerce(TS)":"fx_ts_ecommerce",
 "otel-demo(poly)":"fx_otel",
}
KEYPREDS = ["EXPOSES_ENDPOINT","CALLS_ENDPOINT","DOCUMENTS_ENDPOINT","PRODUCES_EVENT","CONSUMES_EVENT","REFERENCES_EVENT_CHANNEL","CALLS","IMPORTS"]
for label, d in SNAPS.items():
    p = pathlib.Path("data/kg_runs")/d
    if not (p/"facts.jsonl").exists():
        print(f"\n### {label}: MISSING"); continue
    ents=[json.loads(l) for l in (p/"entities.jsonl").read_text().splitlines()]
    facts=[json.loads(l) for l in (p/"facts.jsonl").read_text().splitlines()]
    cov=[json.loads(l) for l in (p/"coverage.jsonl").read_text().splitlines()] if (p/"coverage.jsonl").exists() else []
    man=json.loads((p/"manifest.json").read_text())
    ek=collections.Counter(e["kind"] for e in ents)
    fp=collections.Counter(f["predicate"] for f in facts)
    covstate=collections.Counter(c.get("state") for c in cov)
    covreason=collections.Counter(c.get("scope_ref",{}).get("reason") for c in cov if c.get("state")!="instrumented")
    fbl = man.get("counts",{}).get("files_by_language",{})
    print(f"\n### {label}  [{d}]")
    print("  files_by_language:", dict(fbl))
    print("  entities:", len(ents), "| Service:",ek.get("Service",0),"Endpoint:",ek.get("Endpoint",0),"EventChannel:",ek.get("EventChannel",0),"CodeSymbol:",ek.get("CodeSymbol",0),"CodeModule:",ek.get("CodeModule",0))
    print("  key predicates:", {k:fp.get(k,0) for k in KEYPREDS if fp.get(k,0)})
    print("  coverage states:", dict(covstate))
    if covreason: print("  uninstrumented reasons:", dict(covreason.most_common(6)))
PY
```

Per Run, record: the per-snapshot breakdown, the per-capability scorecard, and what changed
since the prior Run. The scorecard rows are the maturity signal to drive to non-zero.

---

## Backlog (drives the Runs)

Ordered by value. All specs must be AST/decorator/structured — never keyword heuristics.
Each item lists the fixtures that act as its positive test.

1. **.NET events** → `PRODUCES_EVENT` / `CONSUMES_EVENT` / `EventChannel`
   - MassTransit (`IPublishEndpoint.Publish`, `IConsumer<T>.Consume`), eShop `IEventBus.Publish` + `IIntegrationEventHandler<T>`, Azure Service Bus.
   - Tests: `run-aspnetcore` (MassTransit), `eShop` (integration events), `otel` accounting (Kafka consume).
2. **TS events** → `PRODUCES_EVENT` / `CONSUMES_EVENT` / `EventChannel`
   - NestJS `@EventPattern`/`@MessagePattern` (consume) + `ClientProxy.emit`/`.send` (produce); KafkaJS `producer.send`/`consumer.subscribe`; amqplib.
   - Tests: `booking-nestjs` (RabbitMQ), `ts-ecommerce` (KafkaJS).
3. **.NET endpoints** → `EXPOSES_ENDPOINT`
   - ASP.NET Core `[HttpGet]`/`[Route]` controllers + minimal-API `app.MapGet/MapPost`.
   - Tests: `aspnetcore-realworld`, `eShop`, `run-aspnetcore`.
4. **TS endpoints** → `EXPOSES_ENDPOINT` (server) + `CALLS_ENDPOINT` (client)
   - NestJS controller decorators (`@Controller`/`@Get`/`@Post`); client beyond fetch/axios (`superagent`, `got`).
   - Tests: `nestjs-realworld` + `react-realworld` (unlocks cross-repo RealWorld links).
5. **gRPC endpoints** (lower priority, recurring): proto service methods.
   - Tests: `eShop`, `otel` cart, `run-aspnetcore` Discount.

Capability is "mature" when its predicate count is non-zero across its fixtures **and** the
loud-refusal coverage reason for it disappears.

---

## Run log

### Run 1 — Baseline (2026-06-03)

- SuperContext: `main` @ `4d9c1fa` (after #135–#139).
- Fixture commits: aspnetcore-realworld `9feb3fb`, nestjs-realworld `461832d`,
  react-realworld `ee72eba`, eShop `9b4f943`, run-aspnetcore `e3549ab`,
  booking-nestjs `1eeeb94`, ts-ecommerce `2daa00e`, otel `4b8959e`.
- Changed since prior run: n/a (baseline).

**Per-snapshot breakdown**

| Snapshot | files (dotnet/ts/py) | entities | Service | Endpoint | EventChannel | CodeSymbol | EXPOSES_EP | CALLS_EP | DOC_EP | PRODUCES | CONSUMES | REFS | CALLS | IMPORTS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| realworld (x-repo) | 74/92/0 | 899 | 3 | 0 | 0 | 504 | 0 | 0 | 0 | 0 | 0 | 0 | 188 | 752 |
| eShop | 527/11/0 | 3304 | 1 | 26 | 0 | 2444 | 0 | 0 | 40 | 0 | 0 | 0 | 212 | 857 |
| run-aspnetcore | 146/2/0 | 887 | 1 | 0 | 0 | 548 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 209 |
| booking-nestjs | 0/162/0 | 794 | 1 | 0 | 0 | 389 | 0 | 0 | 0 | 0 | 0 | 0 | 389 | 724 |
| ts-ecommerce | 0/55/0 | 199 | 1 | 0 | 0 | 47 | 0 | 0 | 0 | 0 | 0 | 0 | 105 | 185 |
| otel-demo | 11/13/160 | 2294 | 1 | 2 | 0 | 1376 | 2 | 0 | 0 | 0 | 0 | 0 | 344 | 705 |

**Capability scorecard**

| Capability | .NET | TS/JS | Notes |
|---|---|---|---|
| Symbols / modules | ✅ | ✅ | hundreds per repo |
| Intra-repo CALLS | ✅ | ✅ | working |
| IMPORTS | ✅ | ✅ | working |
| Service detection | ✅ | ✅ | 1/repo, realworld=3 |
| **EXPOSES_ENDPOINT** | ❌ 0 | ❌ 0 | ASP.NET controllers + NestJS routes not extracted (eShop's 40 DOCUMENTS_ENDPOINT are OpenAPI-config, not C#) |
| **CALLS_ENDPOINT** | ❌ 0 | ❌ 0 | client extraction is fetch/axios-only; react uses `superagent` |
| **Events (PRODUCES/CONSUMES)** | ❌ 0 | ❌ 0 | extraction is Python-boto3-only; no .NET/TS event specs |
| gRPC endpoints | ❌ 0 | — | not extracted |

**Cross-repo linking (realworld):** 0 endpoint links — neither NestJS routes nor the
`superagent` client are extracted, so the cross-repo HTTP contract produced no edges.

**Loud-refusal coverage (working as intended — names every gap):**
- `parser_backed_js_ts_route_extraction_partial_express_fastify_koa_only` → NestJS uncovered
- `parser_backed_js_ts_client_endpoint_extraction_partial_fetch_axios_only` → superagent/got uncovered
- `no_adapter_for_known_stack` → .NET MassTransit/RabbitMQ messaging
- `unsupported_language` (otel: 9) → Go/Java/etc. correctly refused

**Headline:** symbols/calls/imports are at parity; **endpoints are partial-to-missing and
events are entirely absent for .NET/TS.** Backlog #1 (.NET events) and #2 (TS events) are the
biggest, highest-value gaps.

---

### Run 2 — .NET events (2026-06-03)

- Changed since Run 1: .NET event extraction (MassTransit + integration-event bus), producers +
  consumers, via `dotnet_events.py` + `parser_bridge.py` base-list / generic-arg / binding capture.
- Scope note: targeted measure of the two .NET event fixtures (TS fixtures unchanged from Run 1).

**.NET event facts (was 0 / 0 at Run 1):**

| Snapshot | EventChannel | PRODUCES_EVENT | CONSUMES_EVENT | Cross-service link | Honest coverage rows |
|---|---|---|---|---|---|
| run-aspnetcore | 1 | 1 | 1 | `BasketCheckoutEvent` (Basket→Ordering) | 1 unresolved producer |
| eShop | 14 | 2 | 18 | `GracePeriodConfirmedIntegrationEvent` (produced↔consumed) | unresolved producers → coverage |

**Scorecard movement:**

| Capability | .NET | TS/JS | Note |
|---|---|---|---|
| Events (PRODUCES/CONSUMES) | ⚠️ partial (was ❌) | ❌ 0 | .NET: MassTransit + integration-event bus covered; Azure Service Bus deferred (no fixture). TS unchanged — slices 3–5 pending. |

Unresolvable producers (message type not statically visible, e.g. publishing a method-return or
base-typed parameter) correctly emit `partially_instrumented` coverage rows
(`reason=unresolved_event_message_type`) instead of guessing. No MediatR false positives
(`ISender.Send`/`IMediator.Publish` gated out by receiver type).

### Run 3 — TS NestJS events (2026-06-03)

- Changed since Run 2: TS NestJS microservice event extraction (`@EventPattern`/`@MessagePattern`
  consumers + ClientProxy/ClientKafka `.emit`/`.send` producers) via `ts_parser.mjs`
  `collectMessageEvents` + `typescript_message_transport` adapter.
- Scope note: targeted measure of `ts-ecommerce` (other fixtures unchanged from prior runs).

**TS event facts (was 0 / 0 at Run 1):**

| Snapshot | EventChannel | PRODUCES_EVENT | CONSUMES_EVENT | Notes |
|---|---|---|---|---|
| ts-ecommerce | 11 | 11 | 11 | every channel produced ↔ consumed (order↔inventory↔payment↔product) |

**Scorecard movement:**

| Capability | .NET | TS/JS | Note |
|---|---|---|---|
| Events (PRODUCES/CONSUMES) | ⚠️ partial (MassTransit + integration-event bus) | ⚠️ partial (was ❌) | TS: NestJS microservices covered; raw KafkaJS + amqplib deferred (no validatable fixture). |

Producers gated on receiver typed as a Nest client (no false positives on generic `.emit`/`.send`);
non-literal channels → `unresolved_event_channel` coverage rows rather than guesses.

### Verified full re-measurement (2026-06-03, main after #140 + #141)

Ran the full measurement block across all six fixtures (not targeted numbers) to confirm event
coverage rose where the covered patterns exist and the zeros are honest. Events were 0/0/0
everywhere at Run 1.

| Snapshot | EventChannel | PRODUCES | CONSUMES | verdict |
|---|---:|---:|---:|---|
| eShop (.NET) | 14 | 2 | 18 | ✅ up — MassTransit / integration-event bus |
| run-aspnetcore (.NET) | 1 | 1 | 1 | ✅ up — MassTransit Basket→Ordering |
| ts-ecommerce (TS) | 11 | 11 | 11 | ✅ up — NestJS microservices, full graph |
| realworld (x-repo) | 0 | 0 | 0 | — HTTP-only Conduit API; no event code (endpoints pending) |
| booking-nestjs (TS) | 0 | 0 | 0 | — amqplib wrapper with dynamic exchange/queue names (deferred) |
| otel-demo (poly) | 0 | 0 | 0 | — raw Confluent.Kafka consumer + gRPC; neither covered yet |

`CALLS`/`IMPORTS` unchanged from Run 1 on every fixture → no regression. The three zeros are
genuine "no covered pattern in this repo," not silent failures.

**Discipline (caught in review):** record numbers by re-running the measurement block each pass,
not by citing observed-during-development deltas — the latter drifts (the wave-5 declared-type fix
moved eShop producers 1→2 / channels 13→14 after the Run 2 note was first written).

### Run 4 — .NET endpoints (2026-06-03)

- Changed since Run 3: ASP.NET Core EXPOSES_ENDPOINT extraction (controllers `[HttpVerb("path")]`
  under `[Route("prefix")]`, and minimal APIs `app.MapGet(...)` incl. `MapGroup` prefixes) via
  parser attribute/string-literal/MapGroup capture + `dotnet_endpoints` adapter.
- Verified full re-measurement across all six fixtures (EXPOSES_ENDPOINT was 0 everywhere except
  otel's 2 express rows at Run 1):

| Snapshot | EXPOSES_ENDPOINT | PROD | CONS | note |
|---|---:|---:|---:|---|
| realworld (x-repo) | 19 | 0 | 0 | ✅ from the .NET Conduit controllers (lights up the cross-repo fixture; TS backend + client pending) |
| eShop (.NET) | 29 | 2 | 18 | ✅ minimal APIs incl. MapGroup prefixes (`/api/orders/...`); convention-routed Identity MVC controllers (bare `[HttpGet]`, no literal template) correctly not emitted |
| run-aspnetcore (.NET) | 17 | 1 | 1 | ✅ minimal APIs (`/basket/...`, `/products/...`) |
| otel (poly) | 3 | 0 | 0 | small (+1 .NET) alongside existing express rows |
| booking-nestjs (TS) | 0 | 0 | 0 | — routes are NestJS `@Controller` (TS endpoints, pending) |
| ts-ecommerce (TS) | 0 | 11 | 11 | — same; HTTP routes are NestJS `@Controller` (TS endpoints, pending) |

**Scorecard:** .NET endpoints ❌→✅ (controllers + minimal APIs). TS endpoints still ❌ (NestJS
`@Controller` / superagent client pending — that slice unlocks the RealWorld frontend→backend
cross-repo links). `CALLS`/`IMPORTS`/events unchanged → no regression.

### Run 5 — TS NestJS endpoints (2026-06-03)

- Changed since Run 4: NestJS HTTP controller extraction (`@Controller('prefix')` + `@Get/@Post/...`
  → EXPOSES_ENDPOINT) via `ts_parser.mjs` `collectNestRoutes`, flowing through the existing
  express-routes adapter. Verified full re-measurement:

| Snapshot | EXPOSES_ENDPOINT | PROD | CONS | note |
|---|---:|---:|---:|---|
| realworld (x-repo) | 38 | 0 | 0 | ✅ 19 .NET + 19 NestJS controllers — same Conduit contract in two languages |
| eShop (.NET) | 29 | 2 | 18 | unchanged |
| run-aspnetcore (.NET) | 17 | 1 | 1 | unchanged |
| booking-nestjs (TS) | 19 | 0 | 0 | ✅ NestJS controllers (was 0) |
| ts-ecommerce (TS) | 5 | 11 | 11 | ✅ gateway NestJS controllers (was 0) |
| otel (poly) | 3 | 0 | 0 | unchanged |

**Scorecard:** TS endpoints (server) ❌→✅ (NestJS controllers). `CALLS`/`IMPORTS`/events unchanged.

**Deferred — TS client `CALLS_ENDPOINT`:** the RealWorld frontend (`react-realworld`) uses
`superagent` through a custom `requests.get('/x')` wrapper whose actual superagent call is a
template URL (`` `${API_ROOT}${url}` ``), so the literal path isn't statically resolvable without
bespoke wrapper resolution. No validatable fixture → deferred. Consequence: realworld now exposes
the Conduit contract in both backends, but the frontend→backend cross-repo *link* doesn't form
(no resolvable client CALLS). Honest limitation, not a silent gap.

### Run 6 — FastAPI routes → first cross-language CALLS↔EXPOSES link (2026-06-03)

- Discovery (verify-before-build): the deferred "TS client CALLS" was already handled for
  **axios** (`collectClientEndpointCalls`); building `pawls` showed 8 axios CALLS but 0 EXPOSES.
  The real blocker for the cross-language link was **missing FastAPI route extraction** (only
  Flask/Django existed). So this slice added FastAPI, not a TS client extractor.
- Added `fastapi_routes.extract_fastapi_routes`: `app = FastAPI()` + `@app.get/post/...('/path')`
  and `APIRouter(prefix='/p')` + `@router.get('/x')` → EXPOSES_ENDPOINT. Non-literal paths and
  non-literal router prefixes are skipped.

**New fixture:** `orgs/pawls/pawls` (allenai, Apache-2.0) — TS frontend (`axios.get('/api/...')`)
+ FastAPI backend (`@app.get('/api/...')`).

| Snapshot | EXPOSES_ENDPOINT | CALLS_ENDPOINT | linked paths |
|---|---:|---:|---|
| pawls (TS + FastAPI) | 11 | 7 | **7** (frontend axios ↔ backend FastAPI — first real cross-language CALLS↔EXPOSES link) |

This is the cross-language link the RealWorld fixture couldn't form (react superagent is
wrapper-indirected). Tests: `tests/test_fastapi_routes.py`. No regression (Flask/Django routes
only recognize on their own imports).

### Run 7 — raw KafkaJS events (2026-06-03)

- Added raw `kafkajs` extraction (distinct from the NestJS `ClientKafka` abstraction in Run 3):
  `producer.send({ topic: "t" })` → PRODUCES, `consumer.subscribe({ topic: "t" })` / `{ topics: [...] }`
  → CONSUMES, broker `kafka`. Gated on a `kafkajs` import; the `{ topic: ... }` object-literal arg
  disambiguates the generic `.send`/`.subscribe` names (RxJS `.subscribe(cb)` has no `{topic}`).
  Non-literal topics → coverage.

**New fixture:** `orgs/typescript/payment-processing-microservices` (rehan-adi, MIT).

| Snapshot | PRODUCES | CONSUMES | links |
|---|---:|---:|---|
| payment-microservices | 2 | 2 | `order.create` (order→payment) + `payment.event` (payment→order), both cross-service ✅ |

Tests in `tests/test_typescript_event_extractor.py` (producer/consumer, topics array, import+`{topic}`
gate incl. RxJS-subscribe negative, non-literal→coverage). No regression.

### Run 8 — .NET Azure Service Bus (2026-06-03)

- Added Azure Service Bus to `dotnet_events`: `ServiceBusClient.CreateSender("q")` → PRODUCES,
  `CreateProcessor("q", ...)` / `CreateReceiver("q")` → CONSUMES, broker `azure_servicebus`, channel
  = first string-literal arg. Gated on `Azure.Messaging.ServiceBus`; non-literal entity → coverage.

**New fixture:** `orgs/dotnet/dotnet-aspire-connect-messaging` (Azure-Samples, MIT).

| Snapshot | PRODUCES | CONSUMES | link |
|---|---:|---:|---|
| aspire-messaging | 1 | 1 | `notifications` (ApiService CreateSender → Worker CreateProcessor), cross-service ✅ |

Tests in `tests/test_dotnet_event_extractor.py` (sender/processor, import gate, non-literal→coverage).
No regression (run-aspnetcore 1/1, eShop 2/18).

### Run 9 — (pending: gRPC)
