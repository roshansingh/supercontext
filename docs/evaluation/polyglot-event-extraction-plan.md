# Polyglot Event Extraction Plan (.NET & TS/JS)

Working plan for adding `PRODUCES_EVENT` / `CONSUMES_EVENT` + `EventChannel` extraction to
.NET and TS/JS, to close the biggest gap in
[`polyglot-extraction-maturity.md`](polyglot-extraction-maturity.md) (events = 0 for both
languages at Run 1). Shared so Claude and Codex can revisit and continue.

## Decisions (settled)

- **No new parser.** Grammars already exist: C# via the Python `tree-sitter` C# grammar
  (`source/kg/languages/dotnet/extractors/parser_bridge.py`), TS via the TS Compiler API
  subprocess (`source/kg/languages/typescript/extractors/ts_parser.mjs`). The gap is
  extraction on top (generic type args, decorators, call-arg literals), not parsing.
- **codegraph (`~/work/codegraph`) = semantic reference only, not code to copy.** Its
  `src/resolution/frameworks/nestjs.ts` enumerates the right decorators (`@MessagePattern`
  = request, `@EventPattern` = event, `@Controller`+`@Get` pairing, `@Query` GraphQL-vs-param
  disambiguation) — a good checklist. But it is **regex-over-comment-stripped-source, not AST**,
  which violates our no-regex / parser-AST-first rules, so we reimplement via AST. codegraph
  has **no .NET event detection** (C# = HTTP routes via regex only) — nothing to borrow for
  the .NET slices.
- **AST/structured only, never keyword heuristics.** Channel names come from generic type
  args, decorator string literals, or resolved object-creation types — never from variable
  names or substring matches. Unresolvable channels → loud-refusal `coverage` row, not a guess.
- **Reuse the shared event plumbing**: `event_channel_entity()` + `add_fact()` in
  `source/kg/file_formats/_shared/common.py`; mirror the Python pattern in
  `source/kg/languages/python/extractors/transport_extractor.py` +
  `python_boto3_transport.py` + `transport_apis.py`.

## EventChannel identity conventions

| Framework | broker_kind | channel_address | Notes |
|---|---|---|---|
| MassTransit | `masstransit` | message type name (e.g. `BasketCheckoutEvent`) | MassTransit routes by message TYPE, not a named queue |
| eShop IEventBus | `integration_event` | integration-event type name | type from generic arg / object creation |
| NestJS microservices | `nestjs` | decorator string literal (e.g. `order_created`) | `@EventPattern('x')` / `@MessagePattern('x')` |
| KafkaJS | `kafka` | topic string | from `{ topic: 'x' }` option |
| amqplib | `amqp` | queue/exchange string | from `assertQueue/sendToQueue/consume` first arg |

## Key design nuance — .NET producer type resolution

Consumers are reliable: `class X : IConsumer<T>` / `IIntegrationEventHandler<T>` puts the
type `T` directly in the base list. Producers are harder — the real fixture publishes via
**inferred** generics:

```csharp
await publishEndpoint.Publish(eventMessage, cancellationToken);   // no <T>
```

So the channel is the *static type* of the argument. Resolution order (all AST, no name
heuristics):
1. Explicit generic: `Publish<T>(...)` → `T`.
2. Else resolve the argument's local assignment in the same method: `var eventMessage = new
   BasketCheckoutEvent { ... }` → `BasketCheckoutEvent`.
3. Else → emit a `coverage` row (`reason="unresolved_event_message_type"`, state
   `partially_instrumented`); do **not** guess. Loud refusal, not a wrong channel.

## Slices (each: parser ext → adapter → fixture → validate vs real repo → maturity Run N)

- [x] **Slice 1a — .NET MassTransit consumers.** `class : IConsumer<T>` (gated on
  `using MassTransit`) → CONSUMES_EVENT, channel = message type `T`, broker `masstransit`.
  Parser ext landed: `parser_bridge.py` now emits class `bases` + invocation `type_args`/`method`.
  Logic in `dotnet_events.py`, called from `csharp_extractor._extract_file` so events attach to
  the existing CodeSymbol entities (deviation from "separate adapter" — justified by the single
  .NET extractor architecture; capability `dotnet-csharp-bridge` gained `CONSUMES_EVENT` +
  `EventChannel` + `framework_tags=("masstransit",)`). Validated on `run-aspnetcore`:
  `BasketCheckoutEventHandler → CONSUMES_EVENT → BasketCheckoutEvent`. Tests:
  `tests/test_dotnet_event_extractor.py` (positive + import-gate negative + MediatR
  no-false-positive). Full suite passes.
- [x] **Slice 1b — .NET MassTransit producers.** Done. Parser now captures parameter/field
  receiver-type bindings, local var→type bindings (from `new T()` / generic initializers like
  `Adapt<T>()`), and invocation receiver/first-arg. `dotnet_events._extract_producers` resolves
  the receiver's declared type (`IPublishEndpoint`/`IBus`/`ISendEndpoint`) — disambiguating from
  MediatR `ISender.Send`/`IMediator.Publish` — and the message type via generic arg / inline
  `new T()` / local var; unresolved → `partially_instrumented` coverage row
  (`reason=unresolved_event_message_type`), never a guess. Validated on `run-aspnetcore`:
  Basket→Ordering link formed on `BasketCheckoutEvent` (producer + consumer share the channel).
- [x] **Slice 2 — .NET integration-event bus (eShop).** Done in the same module. Consumers:
  `: IIntegrationEventHandler<T>` (ungated — distinctive name; eShop uses implicit usings) →
  CONSUMES_EVENT, broker `integration_event`. Producers: `IEventBus.Publish/PublishAsync`. Validated
  on `eShop`: 18 consumers, 1 resolved producer (+3 honest coverage rows), cross-service link on
  `GracePeriodConfirmedIntegrationEvent`. Tests in `tests/test_dotnet_event_extractor.py` (7).
- [ ] **(deferred) .NET Azure Service Bus** (`ServiceBusSender.SendMessageAsync`, `ServiceBusProcessor`).
  Neither fixture uses it, so it cannot be validated yet — deferred until a fixture exists rather
  than shipping an unvalidated/guessed extractor.
- [ ] **Slice 3 — TS NestJS.** `@EventPattern('x')`/`@MessagePattern('x')` → CONSUMES;
  `ClientProxy.emit('x')`/`.send('x')` → PRODUCES. Parser ext: emit decorators + their string
  args in `ts_parser.mjs`; emit message-call arg literals. Semantics from codegraph
  `nestjs.ts`. Fixture: `booking-nestjs`.
- [ ] **Slice 4 — TS KafkaJS.** `producer.send({topic})`/`producer.sendBatch` → PRODUCES;
  `consumer.subscribe({topic})` → CONSUMES. Parser ext: capture object-literal `topic` arg.
  Fixture: `ts-ecommerce`.
- [ ] **Slice 5 — TS amqplib (+ .NET Azure Service Bus if present).** `sendToQueue`/`publish`
  → PRODUCES; `consume` → CONSUMES; channel = first string arg.

## Build order per slice (mirror these files)

1. Parser extension — `parser_bridge.py` (`_collect`) for .NET; `ts_parser.mjs` for TS. Add a
   unit test for the new parser output (`tests/languages/...`).
2. Extractor + adapter — new module under the language's `extractors/`, mirroring
   `python_boto3_transport.py` (adapter shell) + `transport_extractor.py` (logic). Capability:
   `produces_predicates=("PRODUCES_EVENT","CONSUMES_EVENT")`, `produces_entity_kinds=("EventChannel",)`,
   `framework_tags=(...)`.
3. Register in the language's `language.py` `adapters()`.
4. Golden fixtures — `tests/adapters/<adapter-name>/golden/{fixture,expected.json}` +
   `false_positive/` (proves the rule isn't over-broad). Run via the adapter-contract test.
5. Validate against the real fixture repo (build_kg) — confirm non-zero PRODUCES/CONSUMES on
   the expected channel.
6. Append a Run to `polyglot-extraction-maturity.md` after a slice (or batch) lands.

## Status

- Run 1 baseline captured (events = 0 both languages).
- **.NET event extraction complete** (slices 1a/1b/2): MassTransit + integration-event bus,
  producers + consumers, with receiver-type disambiguation and loud-refusal coverage.
  Validated on `run-aspnetcore` (1 producer / 1 consumer, Basket→Ordering link) and `eShop`
  (1 producer / 18 consumers, GracePeriodConfirmed link). Azure Service Bus deferred (no fixture).
  Next: TS slices 3 (NestJS) / 4 (KafkaJS) / 5 (amqplib). To be raised as one .NET PR.
