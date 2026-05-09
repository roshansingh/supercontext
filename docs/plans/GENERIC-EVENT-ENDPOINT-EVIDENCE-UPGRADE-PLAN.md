# Generic Event and Endpoint Evidence Upgrade Plan

Status: proposal for debate
Date: 2026-05-09
Purpose: improve goldset answer quality without adding repo-specific or keyword-based logic.

## Goal

Improve KG and EvidencePacket coverage for event lineage and endpoint reconciliation while keeping extraction generic enough for real enterprise codebases.

The immediate validation failures are:

- Q088: missing event producer call sites, scheduling consumer, and downstream delivery-status queue.
- Q100: missing cross-repo endpoint implementation evidence for a documented endpoint.
- Q106: missing event producer send-site, full ARN evidence, and downstream event emission.

These failures should be fixed by generic extraction and retrieval improvements, not by adding client/repo-specific constants.

## Non-Negotiable Guardrails

- Do not hardcode repo, product, domain, tenant, queue, or feature names.
- Do not infer semantics from variable names alone.
- Do not rely on broad keyword lists such as `campaign`, `message`, `queue`, `email`, or project-specific function names.
- Do not emit high-confidence `PRODUCES_EVENT` facts from local wrapper names alone.
- Do not make a query pass by special-casing a goldset ID.

Acceptance check:

```bash
rg -n "ShopAgain|mercury|la-prod|prod_shopagain|campaign" source/kg/extraction source/kg/query source/kg/product
```

Expected: no new hardcoded extraction/query logic. Existing private scenario-plan references are allowed only while goldset code remains in `source/`.

## Design Principle

Use evidence shapes and resolvable dataflow, not keywords.

High-confidence event facts should come from:

- Event-channel literals with recognizable transport shape.
- Config files that declare event sources or queues.
- Calls into known transport/client APIs.
- Local wrappers only when the wrapper body can be resolved to a known transport API.

Lower-confidence facts should be explicit candidates or `REFERENCES_EVENT_CHANNEL`, not silently promoted to canonical producer facts.

## Event Channel Identity

Normalize event-channel evidence into a canonical channel id plus raw metadata.

Examples:

- SQS ARN: `arn:aws:sqs:eu-west-1:123456789012:orders-created`
- SQS queue URL: `https://sqs.eu-west-1.amazonaws.com/123456789012/orders-created`
- Queue name when associated with SQS config: `orders-created`

Canonical form:

```text
sqs:orders-created
```

Metadata to preserve:

- `raw_literal`
- `arn`
- `queue_url`
- `region`
- `account_id`
- `queue_name`
- `source_kind`
- `confidence`

Do not discard raw ARN/URL once normalized. The raw value is required for citations and for later runtime/source verification.

## Python Producer Extraction

### High Confidence: Known Transport APIs

Detect producer calls through known client APIs and resolved call receivers, not variable/function names.

Initial high-confidence Python APIs:

- `boto3.client("sqs").send_message(...)`
- `boto3.client("sqs").send_message_batch(...)`
- `boto3.resource("sqs").Queue(...).send_message(...)`
- `boto3.client("sns").publish(...)`
- Kafka producer `.send(...)` only when receiver type/import resolves to a known Kafka producer package.
- RabbitMQ/Pika `basic_publish(...)` only when receiver/import resolves to `pika`.
- Celery `.delay(...)`, `.apply_async(...)`, or `send_task(...)` only when callee/import resolves to Celery.

Emission:

- `PRODUCES_EVENT` when the channel argument resolves to a channel identity.
- `REFERENCES_EVENT_CHANNEL` when the code references a channel but producer semantics are not proven.

### Medium Confidence: Local Wrapper Resolution

Local wrapper calls are common in real codebases. They must be handled without trusting wrapper names.

Example:

```python
queueMessage(settings.CAMPAIGN_MESSAGE_SQS, payload)
```

Rules:

- If an argument resolves to a known event-channel identity, emit `REFERENCES_EVENT_CHANNEL` at the call site.
- Emit `PRODUCES_EVENT` only if the callee resolves to a local function/method whose body calls a known transport API.
- If the callee cannot be resolved, emit a candidate or lower-confidence fact, not canonical producer evidence.

This means `queueMessage(...)` is not special. Any wrapper name behaves the same if it receives a resolved event-channel argument.

### Dataflow-Lite Resolution

Implement deterministic, bounded value resolution:

- Module constants.
- Imported settings/constants where import target is in the indexed repo.
- `os.getenv("NAME")` references when env/config extraction has a value for `NAME`.
- Simple assignments such as `queue_name = settings.X`.
- Keyword arguments such as `QueueName=settings.X` or `QueueUrl=url`.

Do not attempt full Python execution or dynamic import evaluation in v1.

If a value cannot be resolved:

- Preserve the unresolved expression string.
- Emit a coverage or unknown marker when the unresolved expression blocks a higher-confidence fact.

## Consumer Extraction

Consumer config extraction should preserve both normalized channel and raw source values.

Initial generic sources:

- Zappa SQS event sources.
- Serverless Framework event sources.
- AWS Lambda event-source mappings when present in config.
- Celery task declarations as consumer candidates only when broker routing is explicit.

Emission:

- `CONSUMES_EVENT` for explicit config binding from channel to handler.
- Include handler symbol, config path, line span, stage/environment, raw ARN/URL, normalized channel.

## Endpoint Extraction And Reconciliation

Improve endpoint evidence without repo-specific path filters.

### Extraction

Use generic framework patterns:

- Flask-style decorators: `@app.route(...)`, `@blueprint.route(...)`.
- Flask-style registration calls where statically visible: `add_url_rule(...)`.
- Django URL declarations already supported; preserve existing behavior.
- OpenAPI YAML/JSON docs already supported; preserve existing behavior.

Avoid matching by endpoint path values. The extractor should capture all route declarations it can parse.

### Retrieval

For docs-vs-code questions:

- Retrieve all documented endpoints in scope.
- Retrieve all exposed endpoints from all scoped backend repos.
- Retrieve client `CALLS_ENDPOINT` facts if available.
- If no client call facts exist, report that as coverage weakness rather than treating absence as proof of no callers.

Q100 should improve naturally if the endpoint extractor captures endpoint declarations in every scoped backend repo, not because `/v1/store_data` is special.

## EvidencePacket Changes

Evidence packets should include enough metadata for synthesis and judgement:

- `fact_type`
- `subject`
- `object`
- `repo`
- `path`
- `line_start`
- `line_end`
- `derivation_class`
- `confidence`
- `source_system`
- `qualifier.raw_literal`
- `qualifier.normalized_channel`
- `qualifier.transport`
- `qualifier.handler`
- `qualifier.environment`
- `qualifier.resolution_status`

If a fact is downgraded because wrapper resolution failed, packet should expose that reason.

## Retrieval Plan Changes

Scenario retrieval should use generic surfaces:

- `event-channel --channel X --include-producers --include-consumers --include-references`
- `endpoint-reconciliation --docs-scope A --backend-scope B --client-scope C`
- `event-channel --channel X --include-downstream` only when explicitly requested by the scenario.

No scenario should depend on hardcoded file names or repo names inside generic query code. Private scenario plans may specify scoped repos and target channels because that is test input, not extraction logic.

## Confidence And Promotion Rules

Suggested derivation classes:

- `deterministic_static`: direct known transport API call with resolved channel.
- `authoritative_static`: deployment/event-source config binding channel to handler.
- `static_inferred`: wrapper call with resolved channel but unresolved wrapper body.
- `candidate`: ambiguous wrapper, unresolved value, or conflicting channel identity.

Default operational answers should prefer deterministic/authoritative facts and surface inferred/candidate facts as caveats or explicit candidate evidence.

## Implementation Slices

### PR 1: Channel Normalization And Raw Metadata

- Preserve raw ARN/URL/name in event-channel facts.
- Normalize SQS ARN/URL/name into canonical `sqs:{queue_name}`.
- Add tests for ARN, URL, and plain queue-name normalization.

### PR 2: Python Dataflow-Lite For Event Channels

- Resolve module constants, settings references, simple assignments, and `os.getenv`.
- Emit `REFERENCES_EVENT_CHANNEL` at call sites where an argument resolves to an event channel.
- Do not emit `PRODUCES_EVENT` for wrappers yet.

### PR 3: Known Transport Producer Extraction

- Detect direct SQS/SNS/Kafka/Pika/Celery producer APIs.
- Emit `PRODUCES_EVENT` only when receiver/import and channel resolve.
- Add coverage markers for unresolved producer candidates.

### PR 4: Local Wrapper Promotion

- Resolve local wrapper callee definitions.
- Promote wrapper call-site references to `PRODUCES_EVENT` only when wrapper body calls known transport API.
- Keep unresolved wrappers as `static_inferred` or candidate.

### PR 5: Endpoint Extraction/Reconciliation Coverage

- Capture Flask-style route decorators and `add_url_rule` generically.
- Ensure endpoint reconciliation retrieves all scoped backend endpoints.
- If client call facts are absent, judgement should classify it as evidence weakness, not no-call proof.

## Validation

Run after each PR:

```bash
python -m compileall -q source
python -m source.scripts.run_goldset_answers \
  --snapshot data/kg_runs/latticeai_23 \
  --packets-out data/kg_runs/latticeai_23/goldset_packets_for_answers.json \
  --json-out data/kg_runs/latticeai_23/goldset_answers.json \
  --md-out docs/evaluation/LATTICEAI-GOLDSET-ANSWERS-2026-05-09.md
python -m source.scripts.run_goldset_judgement \
  --packets data/kg_runs/latticeai_23/goldset_packets_for_answers.json \
  --answers data/kg_runs/latticeai_23/goldset_answers.json \
  --json-out data/kg_runs/latticeai_23/goldset_judgement.json \
  --md-out docs/evaluation/LATTICEAI-GOLDSET-JUDGEMENT-2026-05-09.md
```

Expected product movement:

- Q088 moves from Partial toward Pass by adding producer/consumer code paths and downstream channel evidence.
- Q100 moves from Partial toward Pass by including all scoped backend endpoint implementations and accurate client-call coverage status.
- Q106 moves from Partial toward Pass by adding producer send-site and raw ARN evidence.

## Debate Questions

1. Is the proposed confidence ladder strict enough to avoid false producer edges?
2. Should wrapper call sites with resolved channel arguments emit `REFERENCES_EVENT_CHANNEL` only, or a candidate `PRODUCES_EVENT` too?
3. Which known transport APIs should be in v1 without becoming an unmaintainable allowlist?
4. Should endpoint extraction be improved in the same PR sequence, or split into a separate plan?
5. How should unresolved values be represented in coverage so the product can refuse or caveat correctly?
