# Ontology Recommendation — Product 1 v1

- **Status:** Accepted
- **Date:** 2026-04-30
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** `claude-ontology-prior-art-research.md` and `codex-ontology-prior-art-research.md` as decision inputs
- **Binding ADR:** `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- **Debate transcript:** `debates/2-2026-04-30-define-the-final-v1-canonical-ontology-f.md`

---

## Final recommendation

Build Product 1 v1 around **10 canonical node types**, **15 canonical relation types**, **per-node identity tuples**, a **PROV-O-style Entity + Fact + Evidence row shape** with `valid_from`/`valid_to` on evidence rows, qualified facts for role-bearing edges, **5 derivation classes**, **per-entity/per-edge promotion rules**, and a **sidecar `coverage` table** for refusal-on-uninstrumented.

Closed; no further design work needed before `ADR-0006`.

---

## 1. Canonical node types (10)

| # | Node | Semantic definition |
|---|---|---|
| 1 | `Service` | A logical software service deployed and owned by a team. The unit `find_callers` / `blast_radius` / `deploy_blockers_for` operate on. |
| 2 | `Repo` | A git repository hosting source for one or more services / contracts / manifests. Provenance for code evidence per ADR-0005 Mode A binds to `(repo, commit_sha)`. |
| 3 | `Endpoint` | An exposed API operation: REST path+method, gRPC method, or GraphQL root operation field. Operation-level grain. |
| 4 | `Schema` | A versioned, content-addressed contract body (OpenAPI Schema Object / proto message / GraphQL type / AsyncAPI message / JSON Schema). |
| 5 | `EventChannel` | A message broker destination at the protocol level: Kafka topic, NATS subject, SNS topic, AsyncAPI channel address. |
| 6 | `EventMessage` | A typed message contract sent on a channel. AsyncAPI-style separation of channel and message. |
| 7 | `Deployable` | A runnable artifact (Helm release / k8s Deployment / Job / DaemonSet). Identity = the k8s resource identity. |
| 8 | `Deployment` | A specific rollout of a Deployable in an environment at a point in time. Carries `deployed_at`, version, status. |
| 9 | `Environment` | A deployment target (`prod-us-east`, `staging-eu`, `dev`). Per-tenant. |
| 10 | `Owner` | A team or person with ownership over an artifact. Single node kind with `kind` discriminator. |

---

## 2. Canonical relation types (15)

| # | Relation | From → To | One-line semantics |
|---|---|---|---|
| 1 | `OWNS` | `Owner` → `Service`/`Repo`/`Endpoint`/`Schema`/`EventChannel` | Backstage `ownedBy` inverse; ultimate-responsibility ownership. |
| 2 | `DEFINED_IN` | `Service`/`Endpoint`/`Schema`/`EventChannel`/`EventMessage`/`Deployable` → `Repo` | Source-of-truth binding for repo-backed facts; required for ADR-0005 Mode A coordinate fetch. |
| 3 | `IMPLEMENTS` | `Service` → `Endpoint` | Producer-side: this service exposes this endpoint. |
| 4 | `PROVIDES_API` | `Service` → `Schema` | Backstage `providesApi`; service publishes this contract. |
| 5 | `CONSUMES_API` | `Service` → `Schema` | Backstage `consumesApi`; service depends on this contract. |
| 6 | `CALLS` | `Service` → `Endpoint` | Runtime or static evidence of invocation. Distinct from `CONSUMES_API` because `CALLS` is per-operation evidence; `CONSUMES_API` is contract-level intent. |
| 7 | `PRODUCES` | `Service` → `EventMessage` | Service emits this message type. |
| 8 | `CONSUMES` | `Service` → `EventMessage` | Service subscribes to this message type. |
| 9 | `USES_SCHEMA` | `Endpoint`/`EventMessage` → `Schema` | Operation/message references this schema version. Edges carry a required `role` ∈ `{request, response:<status>, parameter:<name>, message_payload, message_header, graphql_input, graphql_output}`. |
| 10 | `CARRIES` | `EventChannel` → `EventMessage` | Channel multiplexes message types. |
| 11 | `RUNS_SERVICE` | `Deployable` → `Service` | Steady-state topology: this deployable artifact runs this service. |
| 12 | `RUNS_IN` | `Deployment` → `Environment` | This deployment instance lives in this environment. |
| 13 | `INSTANCE_OF` | `Deployment` → `Deployable` | This rollout is an instance of this deployable; required to traverse `Service ← RUNS_SERVICE ← Deployable ← INSTANCE_OF ← Deployment → RUNS_IN → Environment` for `deploy_blockers_for`. |
| 14 | `DEPENDS_ON` | `Service` → `Service`/`Schema`/`EventChannel` | Backstage `dependsOn`; broad operational dependency. **Always derived** from corroborated lower-level edges; never primary evidence. |
| 15 | `EVOLVES_TO` | `Schema` → `Schema` | Schema version succession; supports `find_consumers_of_field` and deprecation-campaign tools. |

---

## 3. Identity tuples (all per-tenant)

| Node | Identity tuple |
|---|---|
| `Service` | `(tenant_id, namespace, slug)` — Backstage URN scheme; namespace defaults to `"default"`. |
| `Repo` | `(tenant_id, host, owner, name)` |
| `Endpoint` | REST: `(tenant_id, api_id, normalized_path_template, uppercase_http_method)`; gRPC: `(tenant_id, proto_package, service, method)`; GraphQL: `(tenant_id, schema_id, root_operation_field)` |
| `Schema` | `(tenant_id, format, content_hash)` where `content_hash = SHA-256(canonical_form(body))` |
| `EventChannel` | `(tenant_id, broker_kind, channel_address)` |
| `EventMessage` | `(tenant_id, channel_id, message_name)` |
| `Deployable` | `(tenant_id, cluster, namespace, kind, name)` |
| `Deployment` | `(tenant_id, deployable_id, deployed_at)` |
| `Environment` | `(tenant_id, name)` |
| `Owner` | `(tenant_id, kind, slug)` — `kind` ∈ `{team, person}` |

External URN IDs are per-node-kind, not one global pattern:

- `Service`: `supercontext://service/{namespace}/{slug}`
- `Owner`: `supercontext://owner/{kind}/{slug}`
- `Repo`: `supercontext://repo/{host}/{owner}/{name}`
- `Endpoint`: `supercontext://endpoint/{protocol}/{stable_hash}`
- `Schema`: `supercontext://schema/{format}/{content_hash}`
- `EventChannel`: `supercontext://event-channel/{broker_kind}/{stable_hash}`
- `EventMessage`: `supercontext://event-message/{channel_id}/{message_name}`
- `Deployable`: `supercontext://deployable/{cluster}/{namespace}/{kind}/{name}`
- `Deployment`: `supercontext://deployment/{deployable_id}/{deployed_at}`
- `Environment`: `supercontext://environment/{name}`

`stable_hash` is used where the natural identity tuple is too long or contains unsafe URL characters. It is computed as `SHA-256(canonical_json(identity_tuple))`. Display surfaces may show a short prefix, but the full hash remains available in metadata. MCP responses should include both the URN and the human-readable identity tuple.

URNs are unique only within tenant context because `tenant_id` is carried by connection/session scope, not embedded in the URN. MCP and UI implementers must not treat URNs as globally unique across tenants.

For hash-backed URNs such as `Endpoint` and `EventChannel`, UI surfaces must render the human-readable identity tuple by default and use the URN as the stable machine ID. Opaque hashes should not be the primary human citation.

**REST path normalization rule:** lowercases static segments only when the source format is case-insensitive, strips duplicate slashes, removes trailing slash except at root, and replaces every path parameter token with `{}`. So `/users/{userId}` and `/users/{id}` both become `/users/{}`.

**Schema canonical-form rule (per format):**

- JSON / YAML / OpenAPI / AsyncAPI Schema Objects: RFC 8785 canonical JSON after resolving local `$ref`s within the same document where possible, with non-semantic fields removed (`description`, `examples`, `externalDocs`).
- Protobuf: `protoc`-generated descriptor set bytes with source info removed.
- GraphQL: parsed SDL printed in lexicographic schema order.

**Cross-source merging:** v1 uses a deterministic `Alias` table mapping `(tenant_id, source_system, source_native_id) → canonical_id`. No probabilistic ER (Splink / Senzing / Zingg) in v1.

---

## 4. Entity + Fact + Evidence row shape

PROV-O qualified-relation pattern:

- one **Entity** row per canonical node identity
- one **Fact** row per `(predicate, subject, object, qualifier)`
- multiple **Evidence** rows per Entity or Fact
- AGE nodes and edges are materialized views per ADR-0003 §6

Entities need the same provenance, candidate/canonical status, freshness, and demotion semantics as relation facts. A `Service`, `Endpoint`, `Schema`, or `Deployable` should not become canonical without evidence.

### `entities` table

```
entity_id        uuid PRIMARY KEY
tenant_id        uuid NOT NULL
entity_type      text NOT NULL                -- one of the 10 node types
identity         jsonb NOT NULL               -- normalized identity tuple for the node type
canonical_status text NOT NULL                -- 'candidate' | 'canonical' | 'demoted' | 'archived'
created_at       timestamptz NOT NULL
updated_at       timestamptz NOT NULL
UNIQUE (tenant_id, entity_type, identity)
```

An entity is canonical when `canonical_status='canonical'` and at least one active evidence row exists for it. Candidate entities remain queryable only through candidate / enrichment paths, not default operational answers.

`qualifier` is required so role-bearing relations can be represented without overloading evidence rows. For most relations it is `{}`. For `USES_SCHEMA`, it must contain the bounded `role` value, e.g. `{"role":"request"}`, `{"role":"response:200"}`, or `{"role":"message_payload"}`.

### `facts` table

```
fact_id          uuid PRIMARY KEY
tenant_id        uuid NOT NULL
predicate        text NOT NULL                -- one of the 15 relation types
subject_id       uuid NOT NULL REFERENCES entities(entity_id)
object_id        uuid NOT NULL REFERENCES entities(entity_id)
qualifier        jsonb NOT NULL DEFAULT '{}'  -- relation-specific qualifier; required for USES_SCHEMA.role
canonical_status text NOT NULL                -- 'candidate' | 'canonical' | 'demoted' | 'archived'
created_at       timestamptz NOT NULL
updated_at       timestamptz NOT NULL
UNIQUE (tenant_id, predicate, subject_id, object_id, qualifier)
```

### `evidence` table

```
evidence_id        uuid PRIMARY KEY
entity_id          uuid REFERENCES entities
fact_id            uuid REFERENCES facts
source_system      text NOT NULL              -- backstage | cortex | opslevel | port | compass | github | gitlab | helm | k8s | otel | datadog | tempo | jaeger | spec | static_extractor | llm
source_ref         jsonb NOT NULL             -- source-specific coordinates
extractor          text NOT NULL
extractor_version  text NOT NULL
ingested_at        timestamptz NOT NULL       -- transaction time (when WE saw it)
valid_from         timestamptz NOT NULL       -- modeled-world start
valid_to           timestamptz                -- NULL = still asserts the fact
observed_at        timestamptz                -- source observation time
last_observed_at   timestamptz                -- runtime: last emission; declarative: NULL
derivation_class   text NOT NULL              -- see §5
confidence         numeric                    -- only when derivation_class = 'inferred_llm', else NULL
bytes_ref          jsonb                      -- {repo, commit_sha, path, line_start, line_end} for code evidence; required by ADR-0005 Mode A
evidence_kind      text NOT NULL              -- 'declaration' | 'observation' | 'derivation' | 'annotation'
CHECK ((entity_id IS NOT NULL) <> (fact_id IS NOT NULL))
```

Exactly one of `entity_id` or `fact_id` must be set. Entity evidence proves node existence and identity. Fact evidence proves an edge / relation assertion.

### Materialized AGE edge

For each `(tenant_id, predicate, subject_id, object_id, qualifier)` with `canonical_status='canonical'`, canonical subject/object entities, and at least one evidence row where `now() ∈ [valid_from, valid_to)`:

```
edge.qualifier         = facts.qualifier
edge.derivation_class  = best_tier(evidence.derivation_class)
edge.sources_count     = count(distinct evidence.source_system)
edge.first_observed_at = min(evidence.observed_at)
edge.last_observed_at  = max(evidence.last_observed_at)
edge.valid_from        = min(evidence.valid_from where valid_to is NULL or now() < valid_to)
edge.valid_to          = NULL if any active evidence has NULL valid_to else max(evidence.valid_to)
edge.confidence        = max(evidence.confidence) where derivation_class='inferred_llm', else NULL
edge.last_indexed_at   = max(evidence.ingested_at)
edge.provenance_jsonb  = aggregated array of {source_system, source_ref, evidence_kind}
```

ADR-0003 §6's `provenance_jsonb` becomes a derived shape, not a free-form blob.

### Demotion semantics

A previously canonical entity or fact is demoted by setting `canonical_status='demoted'` and closing active evidence rows with `valid_to=now()` when the source retracts or supersedes them. Hard delete is forbidden (auditability).

An entity is auto-demoted when no active evidence row remains, using the same `valid_to=now()` discipline. This prevents canonical nodes from outliving their source evidence.

---

## 5. Derivation classes

Tier order from strongest to weakest (used by `best_tier()` in the AGE projection):

| # | Class | Source examples |
|---|---|---|
| 1 | `authoritative_declared` | Backstage / Cortex / OpsLevel / Port / Compass catalog declaration |
| 2 | `manual_override` | Human operator wrote it via admin tool |
| 3 | `deterministic_static` | Parsed from OpenAPI / proto / GraphQL / AsyncAPI / Helm / k8s manifest with a deterministic extractor |
| 4 | `runtime_observed` | Seen in OTel trace / Datadog APM / Jaeger / Tempo within configurable freshness window |
| 5 | `inferred_llm` | Claude Agent SDK gap-fill emitted with confidence score; only stored if `confidence >= 0.5` |

`stale` and `unknown_uninstrumented` are **not** derivation classes — they are query-time coverage states (§7).

**Continuous `confidence` is in v1, but only on `inferred_llm` rows.** All other rows have `confidence = NULL`. `sources_count` is the corroboration signal for non-LLM evidence.

`best_tier()` returns the strongest active evidence class by this order. Numerically, that means the lowest tier number wins.

---

## 6. Promotion rules

Promotion is `canonical_status: candidate → canonical` on the Entity or Fact row.

| Edge type | Auto-promote when | Stays candidate when |
|---|---|---|
| `OWNS` | Any `authoritative_declared` or `manual_override` evidence exists | Only CODEOWNERS or repo-convention evidence |
| `DEFINED_IN` | Any `deterministic_static` or `manual_override` evidence | Only LLM inference |
| `IMPLEMENTS` | `deterministic_static` (spec parsed from repo) or `manual_override` | Only inference |
| `PROVIDES_API` | Same as `IMPLEMENTS` | Same |
| `CONSUMES_API` | Either: (a) `manual_override`, OR (b) `runtime_observed` corroboration, OR (c) ConfigMap-injected URL evidence + spec evidence | Only generated-client-code use |
| `CALLS` | `manual_override`, OR any allowlisted high-precision `deterministic_static` typed-client call-site extractor, OR ≥2 distinct `source_system` values across `deterministic_static`/`runtime_observed`, OR ≥10 trace observations within 14 days | Generated-client-code presence only, single low-precision source only, or only inference |
| `PRODUCES` | `manual_override` OR `deterministic_static` (manifest) OR `runtime_observed` within 30 days | Inference only |
| `CONSUMES` | Same as `PRODUCES` | Same |
| `USES_SCHEMA` | `deterministic_static` (parsed from spec) or `manual_override` | Inference only |
| `CARRIES` | `deterministic_static` (AsyncAPI / registry) or `manual_override` | Inference only |
| `RUNS_SERVICE` | `deterministic_static` (Helm/k8s manifest or catalog deploy metadata) or `manual_override` | Inference only |
| `RUNS_IN` | `deterministic_static` (manifest) OR `runtime_observed` OR `manual_override` | Inference only |
| `INSTANCE_OF` | `deterministic_static` (rollout/deployment controller event or manifest-derived deployable identity) OR `runtime_observed` deployment event OR `manual_override` | Inference only |
| `DEPENDS_ON` | Always derived from corroborated lower-level edges (`CALLS`, `CONSUMES_API`, etc.); never primary evidence | n/a |
| `EVOLVES_TO` | `authoritative_declared` (registry) OR `deterministic_static` (spec history with version field) OR `manual_override` | Inference only |

**Rule of thumb:** `inferred_llm` evidence alone never promotes. `manual_override`, ≥2 sources, or ≥1 high-tier deterministic source promotes.

Entity promotion follows the same principle: canonical entities require active non-LLM evidence or a manual override. LLM-only entities remain candidate.

Derived facts such as `DEPENDS_ON` are represented with `evidence_kind='derivation'`. Their `source_ref` must include the underlying fact IDs and derivation rule version, e.g. `{ "derived_from_fact_ids": [...], "rule": "depends_on_from_calls_v1" }`. Their projected `derivation_class` comes from `best_tier()` over the underlying active evidence; derived facts do not introduce a stronger evidence class than their sources.

Derivation rule versions live in code with the extractor / projection implementation and should be surfaced in `source_ref.rule` or `extractor_version` so derived facts can be audited and recomputed after rule changes.

**Numeric thresholds (10 / 14 / 30 days)** are v1 defaults; configurable per tenant; expect adjustment after first design partner data. Runtime freshness windows are per-relation, tenant-overridable.

The allowlist for high-precision `deterministic_static` call-site extractors is an implementation artifact owned by the ingestion / connector module. `ADR-0006` should point to that allowlist as a required implementation input, not define every language/framework rule inline.

---

## 7. Coverage representation

Refusal-on-uninstrumented (PRD §7) requires the graph to know `(subject, predicate, scope)` *coverage*, not just facts.

### `coverage` table (sidecar; not a graph node)

```
coverage_id     uuid PRIMARY KEY
tenant_id       uuid NOT NULL
subject_id      uuid                          -- node we have coverage info for; NULL = global
predicate       text                          -- predicate scope; NULL = all predicates
source_system   text NOT NULL                 -- which source provides the coverage
scope_ref       jsonb                         -- source-specific scope: {repo}, {cluster, namespace}, {service}, {broker}, {trace_dataset}
state           text NOT NULL                 -- 'instrumented' | 'partially_instrumented' | 'uninstrumented' | 'stale'
last_seen_at    timestamptz                   -- last time source emitted ANY signal for this scope
window_start    timestamptz NOT NULL
window_end      timestamptz                   -- NULL = ongoing
```

### Query rule

When a tool needs to refuse-on-uninstrumented for `(subject, predicate)`, it joins to `coverage`:

- `state='instrumented'` AND no fact = **known empty** (e.g., "no callers in the last 30 days")
- `state='partially_instrumented'` = return partial answers only with explicit `coverage_warning`; for safety-critical or completeness-sensitive tools such as `blast_radius` and `deploy_blockers_for`, refuse unless the missing scope is irrelevant to the requested answer
- `state='uninstrumented'` OR no coverage row = **unknown** → refuse
- `state='stale'` → refuse with `reason='stale'`

This adopts CycloneDX's "known empty vs unknown" distinction.

Whether missing scope is irrelevant is a tool-level decision, not a generic ontology decision. Each tool contract must define its own partial-coverage policy and refusal threshold.

---

## 8. Deferred families (out of v1)

Per `PRD.md:215-223` (MVP non-goals) and `PLATFORM-PRD.md:106-126` (Phase 2/3 scope):

**Node types deferred:** `Database`, `FeatureFlag`, `Document`, `Ticket`, `Decision`, `Runbook`, `Incident`, `File`, `CodeSymbol`, `CodeOccurrence`, `RuntimeServiceInstance`, `Person` (collapsed into `Owner`), `Cluster`/`Namespace` (folded into `Deployable` identity tuple).

**Relation types deferred:** `GATES`, `MIGRATES_WITH`, `SHARES_DB_WITH`, `IMPACTED_BY`, `DOCUMENTS`, `MENTIONS`, `RELATES_TO`, `BLOCKS`, `PLANNED_BY`, `RESOLVED_BY`, `MEMBER_OF`.

`deploy_blockers_for` remains in v1, but feature-flag-style `GATES` is deferred. v1 deploy blockers are computed from service dependencies, API/event/schema evolution, and deployment topology — not feature-flag gates.

---

## 9. Open-question resolutions

| # | Question | Resolution |
|---|---|---|
| 1 | Per-tenant vs global namespace | Within-tenant grouping; default `"default"`. Tenant isolation is connection-level per ADR-0003 §6, not a query predicate. |
| 2 | Slug normalization | Lowercase + hyphenate (`a-z0-9-`); **do not** strip suffixes like `-svc`/`-service`. Aliases handle the merge. |
| 3 | Min corroboration thresholds | v1 defaults: N=2 distinct `source_system` values, OR ≥10 `runtime_observed` rows within 14 days. Per-tenant configurable. |
| 4 | Operation vs Endpoint | **Collapse.** `Endpoint` *is* the operation. |
| 5 | Owner polymorphism | Single `Owner` kind with `kind` discriminator. |
| 6 | GraphQL grain | `Endpoint` represents a **root operation field**. Nested fields deferred to Phase 2. |
| 7 | Multi-tenant entity collisions | **Strictly per-tenant.** Aliases cannot cross tenant boundaries. |
| 8 | `inferred_llm` confidence floor | `0.5`. Below: discard, don't even create a candidate Entity or Fact. |
| 9 | Schema canonicalization | Format-specific deterministic canonical form (§3). |
| 10 | `USES_SCHEMA` cardinality | One fact per `(subject, schema, qualifier.role)` with required `role` in `facts.qualifier`. |
| 11 | Runtime freshness windows | Per-relation defaults, tenant-overridable. |
| 12 | Partial coverage behavior | Partial coverage can produce warned partial answers for exploratory tools, but safety-critical or completeness-sensitive tools refuse unless the missing scope is irrelevant. |
| 13 | Node provenance | Canonical nodes are stored as `entities` and require active evidence, same as relation facts. |
| 14 | Derived facts | Derived edges use `evidence_kind='derivation'` with source fact IDs and rule version in `source_ref`. |
| 15 | Tenant-scoped URNs | URNs are tenant-scoped machine IDs; UI surfaces render human-readable identity tuples for hash-backed nodes. |
| 16 | Static extractor allowlist | High-precision call-site extractor allowlist belongs to the ingestion / connector implementation. |

---

## 10. What this rejects from research inputs

- **`unknown_uninstrumented` and `stale` as derivation classes** — coverage states, not derivation properties.
- **`candidate_inferred` as a separate class** — redundant with `inferred_llm` + `canonical_status='candidate'`.
- **`coverage_state` as a per-fact field** — query-time computation over the `coverage` table.
- **`Operation` as separate from `Endpoint`** — collapsed.
- **`RuntimeService` as separate from `Service`** — runtime evidence attaches via `runtime_observed` derivation_class.
- **`SourceFile` as a node** — source coordinates live on `evidence.bytes_ref`.
- **Probabilistic entity resolution (Splink / Senzing / Zingg) in v1** — Phase 2 if alias conflicts force it.

---

## 11. What this preserves for the future

Per `PLATFORM-PRD.md` §11 (Phase 3) and `ADR-0004`'s candidate / enrichment sidecar:

- The 10 v1 nodes and 15 v1 relations are **additive**: Phase 2/3 expansion to docs / tickets / decisions / runbooks / incidents / files joins via new node types and new relations on the same `facts`/`evidence`/`coverage` substrate. No schema rewrite.
- The candidate / enrichment sidecar (ADR-0004) lives next to the canonical graph and reuses the same Entity + Fact + Evidence shape, with `canonical_status='candidate'` on every row.
- Bitemporal queries (`oncall_context_for(since=1h)`-style) become possible because `evidence.valid_from` / `valid_to` plus `evidence.ingested_at` cover the two time axes. XTDB swap (`ADR-0003` §5) remains viable if bitemporal becomes hot.

---

## Historical inputs

- [`claude-ontology-prior-art-research.md`](./claude-ontology-prior-art-research.md)
- [`codex-ontology-prior-art-research.md`](./codex-ontology-prior-art-research.md)
- [`../debates/2-2026-04-30-define-the-final-v1-canonical-ontology-f.md`](../debates/2-2026-04-30-define-the-final-v1-canonical-ontology-f.md)

Read those as research and debate history, not as open decisions.
