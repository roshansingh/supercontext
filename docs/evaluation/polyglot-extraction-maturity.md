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
| eShop | 13 | 1 | 18 | `GracePeriodConfirmedIntegrationEvent` (produced↔consumed) | 3 unresolved producers |

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

### Run 4 — TS endpoints / .NET endpoints (pending)
