# Ontology Prior-Art Research — Claude

- **Status:** Research input, not an ADR
- **Date:** 2026-04-30
- **Author:** Claude
- **Purpose:** Identify ontology prior art SuperContext should borrow before defining the v1 canonical graph ontology. Companion to `codex-ontology-prior-art-research.md`.
- **Anchors:** `PRD.md` §6.1 (engine + provenance), §7 (refusal), `adr/0003-postgres-age-as-initial-graph-storage.md` (storage substrate, schema sketch with `valid_from`/`valid_to`), `adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md` (open ontology question), `docs/graph-building/claude-graph-building-research.md` §7 (multi-source facts and reconciliation), `docs/graph-building/codex-graph-building-research.md` §6, §8, §10 (canonical/candidate split, entity model, confidence model)

---

## 1. Scope and complementarity

`codex-ontology-prior-art-research.md` already establishes the high-level borrowing map: Backstage for catalog entities, OpenTelemetry for runtime, OpenAPI/AsyncAPI/proto/GraphQL for contracts, Kubernetes for deployment, CODEOWNERS for ownership, W3C PROV for provenance vocabulary, CycloneDX for completeness, OpenLineage for facets, SCIP for code intelligence (deferred). That borrowing map is correct and is treated as a baseline here, not re-litigated.

This note focuses on five areas where Codex's coverage is thin or absent and where the v1 ontology decisions need more specificity before ADR-0006 can be written:

1. **Identity rules per node type.** Codex listed entity types but did not specify per-type identity construction.
2. **Promotion rules with thresholds.** Codex deferred this to "manual review for high-risk" — too soft for an operational graph.
3. **Provenance qualification (PROV-O qualified relations).** Codex flattened provenance into a metadata envelope. The qualified-relation pattern is the right shape for v1's confidence/derivation needs.
4. **Bitemporal modeling.** Completely missing from Codex. `ADR-0003` §6 already commits to `valid_from`/`valid_to` columns on edges; the ontology must reflect this.
5. **Confidence aggregation across sources.** Codex's metadata envelope lists `confidence_class` but not the rule for combining evidence from multiple sources for the same edge.

A short additional section covers competitor catalog products (Cortex, OpsLevel, Port, Compass) since SuperContext must ingest from whichever the customer runs.

---

## 2. Identity rules — prior art

Identity is the load-bearing decision the v1 ontology must get right. A weak identity rule means the same service appears as three different nodes from three sources, and downstream queries silently undercount. Codex's note flagged this in passing ("Make identities deterministic and source-coordinate-backed") but did not specify per-type rules.

### 2.1 Backstage URN scheme

`{kind}:{namespace}/{name}` with case-insensitive matching. Names are constrained to `[a-z0-9A-Z]` separated by `[-_.]`, max 63 chars. `metadata.namespace` defaults to `"default"` when unspecified. The system-generated `uid` is intentionally unstable and not suitable as an external reference — only the URN tuple `(kind, namespace, name)` is stable identity.

Two entities are the same iff `(kind, namespace, name)` matches case-insensitively. This is a strong precedent: SuperContext should adopt URN-style canonical IDs, not opaque hashes, so that humans can read citations and the IDs survive reindexing.

Source: https://backstage.io/docs/features/software-catalog/descriptor-format

### 2.2 OpenTelemetry service identity tuple

`(service.namespace, service.name, service.instance.id)` is the documented stable identity for a service across telemetry. `service.name` is required (SDK provides default). `service.namespace` is optional but recommended for grouping. `service.instance.id` is required for instance-level identity (one running process / pod). `service.version` is informational.

Implication: when ingesting traces, SuperContext can pin a `RuntimeService` node to the OTel tuple. The canonical `Service` node is the (namespace, name) pair; the (namespace, name, instance.id) tuple is a `RuntimeServiceInstance` if we need that grain. For v1 we likely do not.

Source: https://opentelemetry.io/docs/specs/semconv/resource/service/

### 2.3 CloudEvents event identity

`(source, id)` must be unique per distinct event produced by the same source. `source` is a URI-reference identifying the producer; `id` is a producer-scoped string. This is a per-event identity, not a per-event-type identity — useful for `EventOccurrence` evidence rows but not for the canonical `EventChannel`/`EventMessage` nodes.

For event-type identity, AsyncAPI's (channel address, message name) pair is the right shape (per Codex §6).

Source: https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md

### 2.4 Kubernetes labels and well-known label set

Kubernetes explicitly says labels are "identifying metadata that is meaningful and relevant to users, but does not directly imply semantics to the core system." Labels are not globally unique. The recommended label set (`app.kubernetes.io/name`, `instance`, `component`, `part-of`, `version`, `managed-by`) is the closest thing to authoritative identity hints, but labels can lie.

Implication: Kubernetes manifests should produce `Deployable` nodes whose identity is `(cluster, namespace, kind, name)` — Kubernetes' own resource identity — not the labels. Labels are evidence that a `Deployable` belongs to a `Service`, not the identity of either.

Source: https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels

### 2.5 Schema identity — content-addressed vs registry-assigned

Two competing precedents:

- **Confluent Schema Registry** assigns global integer IDs to schemas as they are registered. Identity is "whatever the registry says." Cross-registry, IDs collide.
- **Buf Schema Registry** uses module + version + commit SHA. Effectively content-addressed.
- **OpenAPI** has no built-in version identity; specs are typically versioned by `info.version` (an opaque string) plus the file's commit SHA.

Recommendation: hash the canonical-form schema body to produce `Schema.content_hash` (SHA-256). Use `(api_id, normalized_path_template, method)` or `(proto_package, service, method)` for `Operation` identity. Treat `info.version` as evidence, not identity. This survives registry-level changes and matches `ADR-0003` §6's `:Schema.content_hash` field.

### 2.6 Entity-resolution prior art (for cross-source merging)

When the same `Service` appears with different names across sources (Backstage says `payments-svc`, OTel says `payments`, Helm says `payments-api`, CODEOWNERS uses repo path `services/payments`), we have an entity-resolution problem.

Three open-source paths:

| Tool | Approach | Fit for v1 |
|---|---|---|
| **Senzing** | Commercial; fast, deterministic + probabilistic ER engine | Skip — commercial license is incompatible with self-hosted ICP |
| **Zingg** | Apache 2; ML-based ER over Spark | Skip for v1 — Spark adds operational weight |
| **Splink** | MIT; Python; Fellegi-Sunter probabilistic ER | Plausible for offline reconciliation jobs in Phase 2 |

V1 recommendation: do not use a probabilistic ER toolchain. Instead, build a small deterministic resolver:

1. Each ingestion source emits facts with a *source-native ID* (Backstage URN, OTel tuple, k8s resource ID, repo path).
2. Resolver maintains an `Alias` table mapping `(source_system, source_native_id) → canonical_id`.
3. Aliases are seeded by deterministic rules: matching `service.name`, matching `app.kubernetes.io/name`, exact repo path match, etc.
4. Unresolved sources land in a `candidate_alias` table with confidence and source; promotion to canonical alias requires either (a) corroboration from two deterministic sources or (b) operator approval.

Probabilistic ER becomes interesting only when the alias table starts seeing meaningful conflicts; defer until evidence forces it.

---

## 3. Promotion rules — prior art

Codex's note specifies promotion *exists* (canonical vs candidate) but defers the rules to "human review for high-risk." For an operational graph that PR bots and IDE agents query in real time, "human review" is too soft. Need explicit, per-edge-type thresholds.

### 3.1 Backstage processor pipeline

Backstage's pipeline: **EntityProvider → EntityProcessor → Stitcher → final entity**. Providers fetch from sources. Processors transform, validate, and emit relations. The Stitcher merges processor output deterministically — last-write-wins per source, with explicit precedence rules for which source wins on conflict. Critically, processors are idempotent and the stitched entity is a *materialized view* over processor output, not a primary write target.

Source: `docs/graph-building/codex-graph-building-research.md` §5.2 for the same finding distilled from Backstage docs.

This is the right shape for SuperContext: ingestion workers write Facts; canonical edges are the stitched view.

### 3.2 Datomic / XTDB transactor pattern

In Datomic / XTDB, all writes go through a transactor that timestamps each fact. Facts are immutable. The "current entity" is a query-time aggregation over all facts asserted about the entity, possibly retracted. There is no UPDATE — only ASSERT and RETRACT.

Source: https://docs.datomic.com/transactions/transactions.html, https://xtdb.com/

This pattern matches the Fact-row + materialized-edge approach already proposed in `docs/graph-building/claude-graph-building-research.md` §7. Promotion in this model becomes "a higher-confidence Fact supersedes a lower-confidence Fact for the same `(predicate, subject, object, valid_from)` slot." No data is destroyed.

### 3.3 Confluent Schema Registry compatibility checks

Schema evolution is gated by compatibility class: `BACKWARD`, `FORWARD`, `FULL`, `NONE`, plus `*_TRANSITIVE` variants. The registry refuses incompatible writes. This is a different shape of promotion (schema versioning, not fact promotion), but useful precedent for *gated promotion* when the gate is itself programmatic.

Source: https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html

### 3.4 W3C PROV revision

`prov:wasRevisionOf` explicitly models that one entity is a revision of another, preserving provenance to the prior version. PROV does not specify *when* a revision is acceptable — it only provides the vocabulary to record that a revision happened.

Source: https://www.w3.org/TR/prov-o/

### 3.5 Recommended v1 promotion model

Combine the above into a small ruleset:

| Edge type | Promotion threshold |
|---|---|
| `ownedBy` (catalog source) | **Auto-promote** if from authoritative source (Backstage / Cortex / OpsLevel / OPS-LEVEL specifically declared as `authoritative_declared`). Otherwise candidate. |
| `ownedBy` (CODEOWNERS only) | **Candidate**. Promote when corroborated by repo-layout convention or service catalog ownership. |
| `providesApi` | **Auto-promote** when extracted from spec file in repo (deterministic_static) and the service's identity resolves. |
| `consumesApi` | **Candidate** when extracted from generated client SDK use only. **Auto-promote** when corroborated by either (a) a runtime trace edge or (b) ConfigMap-injected URL. |
| `calls` | **Candidate** if from one source. **Auto-promote** when corroborated by ≥2 sources (e.g., static call site + trace), OR seen in trace data N times across W days (configurable, defaults TBD by benchmark). |
| `produces` / `consumes` (events) | **Auto-promote** from manifest declaration. **Candidate** from inference. **Auto-promote** when seen in trace within last 30 days. |
| `dependsOn` (deploy) | **Auto-promote** from manifest. |
| `derivedFrom` | Always canonical (this is provenance, not domain edge). |
| LLM-inferred edges | **Always candidate**, never auto-promoted. Surfaced separately in MCP responses. |

The thresholds are starting points; v1 should make them configurable and adjust based on first design partner data.

---

## 4. Provenance qualification — PROV-O qualified relations

Codex's metadata envelope flattens provenance into a single record per fact (`source_system`, `source_ref`, `extractor`, `extractor_version`, `ingested_at`, etc.). That works for the common case but loses information when one fact is supported by multiple kinds of evidence with different roles.

PROV-O has a documented solution: **qualified relations**.

### 4.1 The pattern

Instead of a binary relation `entity wasGeneratedBy activity`, PROV-O lets you express the same relation as a triple plus a qualification class:

```
Fact -- prov:wasGeneratedBy --> Activity        (binary, simple case)
Fact -- prov:qualifiedGeneration --> Generation
Generation -- prov:activity --> Activity
Generation -- prov:atTime --> "2026-04-30T12:00:00Z"
Generation -- prov:hadRole --> "static_extractor"
```

The `Generation` intermediate node carries the role, time, and any other qualifying attributes. Same pattern for `prov:Usage`, `prov:Derivation`, `prov:Attribution`, `prov:Association`.

Source: https://www.w3.org/TR/prov-o/

### 4.2 Why this matters for SuperContext

The SuperContext runtime needs to answer questions like: "this `calls` edge — was it confirmed by a static extractor at this commit, by a trace at this trace_id and time, or by an LLM gap-fill?" A flat envelope makes that a parsing problem. A qualified-relation shape makes it a join.

Concrete v1 mapping (Postgres + AGE):

- `Fact` row: `(fact_id, predicate, subject_id, object_id, valid_from, valid_to)`. No source-system in this row.
- `Evidence` row: `(evidence_id, fact_id, source_system, source_ref, extractor, extractor_version, observed_at, confidence, derivation_class)`. Many `Evidence` rows per `Fact`.
- Materialized edge in AGE: aggregates over `Evidence` rows for each `Fact`.

This is the same shape `docs/graph-building/claude-graph-building-research.md` §7 already proposed (separate `Fact` rows per source). PROV-O qualified relations gives us the vocabulary to justify it.

### 4.3 What to skip

PROV-O's full OWL ontology with `prov:Bundle`, `prov:Plan`, `prov:Influence`, `prov:Communication`, `prov:Delegation` etc. is overkill. Adopt the qualified-relation pattern only; don't try to be PROV-O conformant.

---

## 5. Bitemporal modeling — prior art

Completely absent from Codex's note, but `ADR-0003` §6 already commits to `valid_from`/`valid_to` columns on every edge. The ontology must define what they mean.

### 5.1 The two time axes

Bitemporal modeling distinguishes:

- **Valid time** (a.k.a. application time): when a fact is true in the modeled world. E.g., service A called service B between 2026-03-01 and 2026-04-15.
- **Transaction time** (a.k.a. system time): when SuperContext recorded the fact. E.g., we ingested this edge on 2026-04-29.

A fact has two ranges; queries can ask "what did the graph say *now* about what the world was like *then*" (valid-time query at current transaction time) or "what did the graph believe *yesterday* about the world *as of yesterday*" (full bitemporal query).

Source: https://en.wikipedia.org/wiki/Temporal_database, https://docs.xtdb.com/concepts/bitemporality.html

### 5.2 Datomic / XTDB

Datomic and XTDB v2 implement full bitemporal natively. Every datom carries `tx_time` (transaction time) automatically. Datomic adds `valid_time` as a user-managed attribute; XTDB v2 makes both first-class.

Sources: https://docs.xtdb.com/concepts/bitemporality.html, https://docs.datomic.com/

### 5.3 SuperContext mapping

Postgres + AGE does not natively bitemporal. Recommendations:

- **`valid_from`, `valid_to`** on every `Evidence` row: the modeled-world window. `NULL` `valid_to` = still valid.
- **`ingested_at`** on every `Evidence` row: the transaction time. Append-only, immutable.
- **`last_observed_at`** for runtime evidence: the most recent time the underlying source emitted this signal. For trace-derived edges, this is the freshness signal `oncall_context_for(since=1h)` and similar future tools will need.
- **Soft-delete** is `valid_to = now()` on the `Evidence` row. Hard-delete is forbidden (auditability).

Bitemporal queries ("what did we believe last Tuesday about the calls between A and B as of last Wednesday") become possible by filtering Evidence rows on both `ingested_at <= T_q1` and `valid_from <= T_q2 < valid_to`. Complex query, but rare; v1 likely needs only `as-of-now` valid-time queries.

Future XTDB swap remains viable per `ADR-0003` §5 if bitemporal becomes hot.

---

## 6. Confidence aggregation — prior art

`docs/graph-building/claude-graph-building-research.md` §8 open question #6 explicitly flagged confidence aggregation across sources as undecided. Prior art suggests three approaches:

### 6.1 Max confidence

`confidence(edge) = max(confidence(evidence_i))`. Simple, defensible: the strongest evidence wins. Loses information about corroboration.

### 6.2 Independence-assumption Bayesian

`confidence(edge) = 1 - prod(1 - confidence(evidence_i))`. Two pieces of evidence at 0.7 confidence yield 0.91. Assumes evidence is independent (rarely true; static extraction and runtime trace both depend on the code being deployed).

### 6.3 Dempster-Shafer

Combines belief masses over a frame of discernment. More general than Bayesian, handles disagreement (one source says yes, another says no). Mathematically heavy; rarely worth it for SuperContext's signals.

### 6.4 Discrete tier with explicit corroboration count

`derivation_class` is one of `authoritative_declared`, `deterministic_static`, `runtime_observed`, `manual_override`, `candidate_llm`, `unknown_uninstrumented`, `stale`. Continuous `confidence` only present where a source emits one (e.g., LLM logprob). Corroboration count (`len(distinct sources)`) is a separate field.

### 6.5 Recommendation

Use **(6.4) discrete tier + corroboration count** for v1. Skip continuous Bayesian and Dempster-Shafer. Reasoning:

- The PR-bot and refusal logic want categorical answers ("this edge is observed in production" vs "this edge is inferred"), not a 0.83 number.
- Continuous confidence on heterogeneous sources (LLM logprob vs trace count vs catalog declaration) is comparing apples to oranges.
- Corroboration count (`sources_count >= 2`) is the cheap, legible signal that catches multi-source agreement without aggregation math.
- Reserve continuous `confidence` for the LLM-inferred edges in the candidate sidecar (per `ADR-0004`), where the model emits one natively.

Aggregation rule for v1:

```
edge.derivation_class = max_tier(evidence_tiers)   # tier order: authoritative > deterministic_static > runtime_observed > inferred > candidate
edge.sources_count = len(distinct evidence.source_system)
edge.last_observed_at = max(evidence.observed_at)
edge.first_observed_at = min(evidence.observed_at)
edge.confidence = NULL unless any evidence is candidate_llm, in which case max(candidate_llm confidence)
```

If we later need a real probabilistic model, switch to Bayesian; until then this is enough.

---

## 7. Cortex / OpsLevel / Port / Compass — competitor catalogs

Codex's note focused on Backstage but did not survey the proprietary IDPs SuperContext must ingest from per `PRD.md` §6.1 (5th ingestion source family is "service catalog").

### 7.1 Cortex

- Entities: `Service`, `Resource`, `Domain`, `Team`. Cortex Service has built-in fields for ownership, dependencies, on-call, lifecycle.
- Relations: `dependsOn`, `ownedBy`, `partOfDomain`. Custom relationships via Resource Definitions.
- Catalog API: REST + GraphQL.

Source: https://docs.cortex.io/docs/reference/basics/entities

### 7.2 OpsLevel

- Entities: `Service`, `Team`, `Tier`, `Lifecycle`, `System`, `Domain`, `Infrastructure Resource`.
- Relations: ownership (Team→Service), dependencies (Service→Service), system membership.
- Catalog API: GraphQL.

Source: https://docs.opslevel.com/docs/services

### 7.3 Port

- Entirely generic: customers define their own `Blueprint` (entity type) and `Relation` schemas. There is no fixed taxonomy.
- Implication: Port ingestion has to be customer-by-customer. Get the Blueprint definitions from the API and project them.

Source: https://docs.port.io/build-your-software-catalog/

### 7.4 Atlassian Compass

- Entities: `Component` (similar to Backstage), `Team`. Tracks libraries and dependencies.
- Catalog API: GraphQL.

Source: https://developer.atlassian.com/cloud/compass/

### 7.5 Implication

The SuperContext canonical ontology should be a **superset of the union** of these catalog models, with each catalog's specific terms mapped via aliases. Concrete claims to verify in v1 prototype:

- All four expose Service, Team, Domain or System.
- All four expose ownership.
- Cortex, OpsLevel, Compass expose dependency edges natively; Port requires customer-defined Blueprint.

The v1 ontology relation `ownedBy` should accept evidence from any of: Backstage, Cortex, OpsLevel, Port (with Blueprint mapping), Compass, CODEOWNERS, or repo conventions. None should be the only source of truth.

---

## 8. What I'd add or change vs. Codex's note

**Endorse without change:**

- The Backstage / OTel / OpenAPI / AsyncAPI / Kubernetes / CODEOWNERS borrowing matrix.
- The 5-axis design rules (small core, no source-overfit, runtime separate from declared, etc.).
- The recommended next step: write `ADR-0006: Define the Product 1 Canonical Ontology and Fact Metadata Envelope`.

**Add to the borrowing matrix:**

- **Datomic / XTDB**: borrow immutable-fact + bitemporal vocabulary; do not borrow runtime.
- **PROV-O qualified relations** (not just PROV-O entity/activity/agent): borrow the qualification pattern for confidence/derivation.
- **Cortex / OpsLevel / Port / Compass**: borrow nothing structurally (each is a proprietary catalog), but commit to ingest connectors for all four behind a uniform `ownedBy` / `dependsOn` projection.
- **Splink**: track as Phase 2 candidate for offline alias reconciliation; explicitly skip Senzing / Zingg.

**Tighten Codex's metadata envelope:**

- Rename `derivation_class` and `confidence_class` to be the same field — one categorical `derivation_class` per evidence row, with an optional continuous `confidence` only where a source emits one.
- Split provenance into a separate `Evidence` row per source rather than a flat envelope on the fact, per §4.2 above.
- Add explicit `valid_from`/`valid_to` per evidence row (not per fact), aligned with `ADR-0003` §6.
- Make `coverage_state` a query-time computation over fact + edge-type expectation, not a stored field.

**Add identity rules section to ADR-0006:**

Per-node-type identity construction:

| Node | Identity tuple |
|---|---|
| `Service` | `(tenant_id, namespace, slug)` — slug is human-readable; namespace defaults to `"default"` |
| `Repo` | `(tenant_id, host, owner, name)` (e.g., `(t1, github.com, acme, payments)`) |
| `Endpoint` | `(api_id, normalized_path_template, http_method)` for REST; `(proto_package, service, method)` for gRPC; `(graphql_schema_id, root_field_path)` for GraphQL |
| `Schema` | `(format, content_hash)` where `content_hash` = SHA-256 of canonical-form schema body |
| `EventChannel` | `(broker_kind, channel_address)` — e.g., `("kafka", "orders.created.v3")` |
| `EventMessage` | `(channel_id, message_name)` — AsyncAPI separation |
| `Deployable` | `(cluster, namespace, kind, name)` — Kubernetes resource identity |
| `Owner` | `(tenant_id, kind, slug)` — kind ∈ `{team, person}` |

URN-style external IDs: `supercontext://service/{namespace}/{slug}` so MCP citations are human-readable.

**Add promotion rules section to ADR-0006:**

Per-edge-type promotion thresholds per §3.5 above. Make thresholds configurable.

---

## 9. Open questions for ADR-0006

1. **Per-tenant vs global namespace.** Backstage's `metadata.namespace` is per-catalog; SuperContext's tenant model already isolates per-tenant (see `ADR-0003` §6). Do we keep `namespace` as a within-tenant grouping or collapse it to tenant-level?
2. **Slug normalization rules.** Lowercase + hyphenate? Strip suffix `-svc`/`-service`? Risk: collapsing distinct services. Risk of not collapsing: same logical service appears as both `payments` and `payments-svc`.
3. **Minimum corroboration thresholds.** §3.5 leaves N (count) and W (window) configurable. What are the v1 defaults? Need first-design-partner data.
4. **`Operation` vs `Endpoint` distinction.** Codex's §3 distinguishes these (`Operation` for the OpenAPI Operation Object, `Endpoint` for REST path+method). Does v1 keep both or collapse `Operation` into `Endpoint`?
5. **`Owner` polymorphism.** Backstage separates `Group` (team) and `User` (person) as distinct kinds. We have `Owner` with `kind` discriminator. Either is fine; pick one for v1 and stick.
6. **GraphQL field grain.** Per Codex §3.5 above, GraphQL fields are not REST endpoints. Do v1 callers/callees queries return fields, root operations, or both?
7. **Multi-tenant entity collisions.** Even with per-tenant namespace, what happens when two tenants share a published OpenAPI spec (e.g., a shared internal API)? Probably "graph is per-tenant, never shared."
8. **Confidence floor for canonical promotion.** §6.5 keeps continuous confidence out of v1 mostly, but LLM-inferred candidate edges have it. What's the floor below which we don't even store?

---

## 10. Sources

### Already cited by codex-ontology-prior-art-research.md
- Backstage descriptor: https://backstage.io/docs/features/software-catalog/descriptor-format
- Backstage well-known relations: https://backstage.io/docs/features/software-catalog/well-known-relations/
- OpenTelemetry semconv: https://opentelemetry.io/docs/specs/semconv/
- OpenAPI 3.1.1: https://spec.openapis.org/oas/v3.1.1.html
- AsyncAPI 3.0.0: https://www.asyncapi.com/docs/reference/specification/v3.0.0
- Protocol Buffers proto3: https://protobuf.dev/reference/protobuf/proto3-spec/
- GraphQL Spec: https://spec.graphql.org/
- Kubernetes labels: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/
- W3C PROV overview: https://www.w3.org/TR/prov-overview/
- W3C PROV namespace: https://www.w3.org/ns/prov/
- CycloneDX: https://cyclonedx.org/specification/overview
- OpenLineage: https://openlineage.io/docs/spec/object-model
- SCIP: https://github.com/sourcegraph/scip/

### Additional sources for sections in this note
- W3C PROV-O ontology + qualified relations: https://www.w3.org/TR/prov-o/
- OpenTelemetry service identity: https://opentelemetry.io/docs/specs/semconv/resource/service/
- CloudEvents spec: https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md
- OpenLineage facets: https://openlineage.io/docs/next/spec/facets/
- Glean Angle codemarkup schema: https://github.com/facebookincubator/Glean/blob/main/glean/schema/source/codemarkup.angle
- Datomic transactions: https://docs.datomic.com/transactions/transactions.html
- XTDB bitemporality: https://docs.xtdb.com/concepts/bitemporality.html
- Confluent Schema Registry compatibility: https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html
- Cortex entities: https://docs.cortex.io/docs/reference/basics/entities
- OpsLevel services: https://docs.opslevel.com/docs/services
- Port catalog: https://docs.port.io/build-your-software-catalog/
- Atlassian Compass: https://developer.atlassian.com/cloud/compass/
- Splink (probabilistic ER): https://github.com/moj-analytical-services/splink
- Senzing: https://senzing.com/
- Zingg: https://github.com/zinggAI/zingg
- Bitemporal modeling: https://en.wikipedia.org/wiki/Temporal_database

---

**Bottom line:** Codex's borrowing map is right. This note adds five things ADR-0006 needs that Codex's covered lightly or not at all: (1) per-node-type identity rules, (2) per-edge-type promotion thresholds, (3) PROV-O qualified-relation shape for evidence, (4) bitemporal `valid_time` / `transaction_time` discipline aligned with `ADR-0003` §6, and (5) discrete-tier confidence with corroboration count rather than continuous Bayesian aggregation. Plus the Cortex / OpsLevel / Port / Compass survey for the catalog ingestion connectors v1 must build.
