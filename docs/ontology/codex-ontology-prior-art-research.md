# Ontology Prior Art Research

- **Status:** Research input, not an ADR
- **Date:** 2026-04-30
- **Author:** Codex
- **Purpose:** Identify ontology and schema prior art SuperContext should borrow from before defining the v1 canonical graph ontology.

---

## Executive recommendation

Do **not** invent the Product 1 ontology from scratch.

Use a small canonical ontology that borrows from established models:

- **Backstage Software Catalog** for service/catalog entities and ownership/dependency relations.
- **OpenTelemetry Semantic Conventions** for runtime-observed service, HTTP, RPC, messaging, database, and trace facts.
- **OpenAPI / gRPC / GraphQL / AsyncAPI** for contract-level operations, schemas, messages, and API/event semantics.
- **Kubernetes labels, selectors, owner references, and recommended labels** for deployment topology and deployable identity.
- **CODEOWNERS / service catalogs** for ownership evidence.
- **W3C PROV** for provenance vocabulary.
- **CycloneDX dependency graph concepts** for dependency completeness/unknown semantics.
- **OpenLineage facets** as inspiration for future platform expansion into jobs, datasets, docs, and operational metadata.
- **SCIP / LSIF** as future code-intelligence inputs, not as Product 1's core ontology.

The v1 ontology should be **SuperContext-native**, but the vocabulary should intentionally map to these standards so connectors stay modular and the later platform graph can grow without a rewrite.

---

## Borrowing map

| Area | Borrow from | What to borrow | What not to borrow |
|---|---|---|---|
| Service/catalog model | Backstage | `Component`, `API`, `Resource`, `System`, `Domain`, `Group/User`; relations like `ownedBy`, `partOf`, `providesApi`, `consumesApi`, `dependsOn` | Backstage's UI/catalog-specific assumptions as the only source of truth |
| Runtime service identity | OpenTelemetry | `service.namespace`, `service.name`, `service.instance.id`, HTTP/RPC/messaging/db semantic attributes | Raw span shape as canonical graph shape |
| HTTP APIs | OpenAPI | `paths`, HTTP methods, Operation Object, `operationId`, parameters, request bodies, responses, security | Treating docs-only descriptions as enough to prove live callers |
| gRPC/protobuf | gRPC/protobuf | service, rpc method, request/response messages, streaming shape, package names | Assuming generated client code proves runtime usage |
| GraphQL | GraphQL schema/introspection | schema, type, field, argument, query/mutation/subscription entry points | Collapsing GraphQL fields into REST endpoints |
| Events/messaging | AsyncAPI + OTel messaging | channel, operation `send`/`receive`, message, payload schema, `messaging.destination.name`, `messaging.operation.type` | Assuming topic name alone uniquely defines event semantics |
| Deployment topology | Kubernetes | workload/service/resource identity from labels/selectors; owner references; recommended `app.kubernetes.io/*` labels | Treating labels as globally unique or always trustworthy |
| Ownership | CODEOWNERS + service catalog | file/path ownership, team/group ownership, authoritative catalog ownership | Treating CODEOWNERS alone as business/service ownership |
| Provenance | W3C PROV | entity/activity/agent mental model; generated/derived/attributed relationships | Full semantic-web complexity |
| Dependency completeness | CycloneDX | dependency graph with explicit references and unknown/incomplete graph semantics | SBOM component taxonomy as the Product 1 graph |
| Future platform lineage | OpenLineage | extensible facets, run/job/dataset event model, source-code-location/version facets | Making data lineage a Product 1 requirement |
| Code intelligence | SCIP / LSIF | symbol occurrence, definition/reference, source range, language-agnostic index concepts | Broad language indexer integration in v1 |

---

## Source-by-source findings

### 1. Backstage Software Catalog

Backstage is the closest prior art for Product 1's service/catalog ontology.

Useful concepts:

- `Component`: maps well to `Service` or a broader `SoftwareComponent`.
- `API`: maps to exposed API contracts.
- `Resource`: maps to database, queue, bucket, topic, cache, or other operational dependencies.
- `System` and `Domain`: useful later for grouping services into larger bounded contexts.
- `Group` / `User`: maps to ownership.
- Relations: `ownedBy`, `ownerOf`, `partOf`, `hasPart`, `providesApi`, `apiProvidedBy`, `consumesApi`, `apiConsumedBy`, `dependsOn`, `dependencyOf`.

Important lesson:

Backstage separates declared entity specs from generated/read-only relations. It explicitly treats relations as derived by processors from source data and encourages consumers to use relations as the authoritative relationship surface. That maps directly to our canonical fact projection model.

Implication for SuperContext:

- Use Backstage relation names where they fit: `ownedBy`, `partOf`, `providesApi`, `consumesApi`, `dependsOn`.
- Do not name everything `calls`. Keep `calls` for runtime/static invocation edges and use `dependsOn` for broader operational dependencies.
- Support importing Backstage catalog facts as authoritative or high-confidence source facts, but do not require Backstage.

Sources:

- Backstage descriptor format: https://backstage.io/docs/features/software-catalog/descriptor-format
- Backstage well-known relations: https://backstage.io/docs/features/software-catalog/well-known-relations/
- Backstage `ownedBy`: https://backstage.io/docs/reference/catalog-model.relation_owned_by
- Backstage `providesApi`: https://backstage.io/docs/reference/catalog-model.relation_provides_api

### 2. OpenTelemetry Semantic Conventions

OpenTelemetry is the strongest prior art for runtime-observed facts.

Useful concepts:

- Resource identity: `service.namespace`, `service.name`, `service.instance.id`, service version.
- HTTP spans: method, route, path, server address/port, status code, error type.
- RPC spans: RPC system, method, service/server address, status.
- Messaging spans: messaging system, destination name, operation name/type, producer/consumer semantics.
- Database spans: database system and operation semantics.
- CloudEvents conventions: useful if event payloads follow CloudEvents.

Important lesson:

OTel's conventions are designed for polyglot systems. They provide a common naming scheme across languages and frameworks, which is exactly what Product 1 needs for multi-language enterprise support.

Implication for SuperContext:

- Runtime-observed edges should store OTel-derived attributes separately from canonical relationship names.
- `Service` identity should align with OTel service identity when traces are available, but not depend on traces as the only source.
- Canonical edges should distinguish:
  - `calls` from HTTP/RPC spans
  - `produces` / `consumes` from messaging spans
  - `queries` or `dependsOn` for database spans, if database support enters v1
- Runtime facts should carry `last_observed_at`, sample/window metadata, trace IDs, and traffic evidence.

Sources:

- OTel semantic conventions overview: https://opentelemetry.io/docs/specs/semconv/
- OTel service semantic conventions: https://opentelemetry.io/docs/specs/semconv/resource/service/
- OTel HTTP spans: https://opentelemetry.io/docs/specs/semconv/http/http-spans/
- OTel RPC spans: https://opentelemetry.io/docs/specs/semconv/rpc/rpc-spans/
- OTel messaging spans: https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/
- OTel database spans: https://opentelemetry.io/docs/specs/semconv/database/database-spans/
- OTel CloudEvents spans: https://opentelemetry.io/docs/specs/semconv/cloudevents/cloudevents-spans/

### 3. OpenAPI

OpenAPI is the correct source of truth for HTTP contract entities.

Useful concepts:

- API document
- server/base URL
- path
- HTTP method
- Operation Object
- `operationId`
- parameters
- request body
- responses
- schemas/components
- security requirements

Important lesson:

OpenAPI describes capability, not actual usage. It proves an API operation exists, but it does not prove who calls it.

Implication for SuperContext:

- Model OpenAPI facts as `ApiContract`, `Endpoint`, `Operation`, and `Schema` facts.
- Use `operationId` when present, but identity must fall back to `(api_id, normalized_path_template, method)` because many specs have missing or unstable operation IDs.
- Producer-side contract edges can be canonical if the spec is committed and owned.
- Consumer/caller edges need static call-site evidence, runtime trace evidence, or authoritative catalog evidence.

Sources:

- OpenAPI Specification 3.1.1: https://spec.openapis.org/oas/v3.1.1.html
- OpenAPI endpoints guide: https://learn.openapis.org/specification/paths.html

### 4. gRPC and Protocol Buffers

gRPC/protobuf is the correct source of truth for RPC contract entities.

Useful concepts:

- package
- service
- rpc method
- request message
- response message
- unary/server-streaming/client-streaming/bidirectional-streaming method type
- message/field schema

Important lesson:

The `.proto` file gives a stronger machine-readable identity than many REST specs because service/method/message names are part of the generated API surface.

Implication for SuperContext:

- Model `RpcService`, `RpcMethod`, and `Schema` or map them into `API` / `Operation` / `Schema` with protocol-specific attributes.
- Identity should include proto package + service + method.
- Streaming shape should be explicit metadata because it affects blast-radius and migration semantics.

Sources:

- gRPC core concepts: https://grpc.io/docs/what-is-grpc/core-concepts/
- Protocol Buffers proto3 specification: https://protobuf.dev/reference/protobuf/proto3-spec/

### 5. GraphQL

GraphQL should be treated as a contract source with a different shape than REST.

Useful concepts:

- schema
- object type
- field
- argument
- query/mutation/subscription root fields
- introspection as a way to discover schema shape

Important lesson:

GraphQL does not map cleanly to REST endpoints. The stable operational unit is usually a field path or root operation field, not an HTTP path.

Implication for SuperContext:

- Model GraphQL as `GraphqlSchema`, `GraphqlType`, `GraphqlField`, and `GraphqlOperationSurface`, or normalize into `API` / `Operation` with `protocol=graphql`.
- Avoid pretending each GraphQL field is an HTTP endpoint.
- Caller evidence likely needs static query extraction or persisted operation registries, not just server schema.

Sources:

- GraphQL Specification: https://spec.graphql.org/

### 6. AsyncAPI

AsyncAPI is the strongest prior art for event/message contracts.

Useful concepts:

- channel
- channel address
- operation
- operation action: `send` or `receive`
- message
- payload schema
- correlation ID
- protocol binding
- reusable components/messages

Important lesson:

AsyncAPI separates channel, operation, and message. This is the right shape for SuperContext. A Kafka topic alone is not enough to identify semantic event contracts because multiple message types may travel on one destination.

Implication for SuperContext:

- v1 should model `EventChannel` / `Topic`, `EventMessage`, and `EventSchema`.
- `produces` and `consumes` should connect services to message/channel semantics, not only raw topic strings.
- If only topic names are available, create canonical low-detail topic facts but keep message/schema semantics unknown.

Sources:

- AsyncAPI document structure: https://www.asyncapi.com/docs/concepts/asyncapi-document/structure
- AsyncAPI operations: https://www.asyncapi.com/docs/concepts/asyncapi-document/adding-operations
- AsyncAPI messages: https://www.asyncapi.com/docs/concepts/asyncapi-document/adding-messages
- AsyncAPI 3.0.0 specification: https://www.asyncapi.com/docs/reference/specification/v3.0.0

### 7. Kubernetes

Kubernetes is the best source for deployment topology and deployable identity when manifests are available.

Useful concepts:

- labels and selectors
- recommended `app.kubernetes.io/*` labels
- owner references
- Service selectors pointing to Pods / workloads
- annotations for non-identifying metadata

Important lesson:

Kubernetes explicitly says labels are identifying/queryable metadata, while annotations are non-identifying metadata. It also says labels are not globally unique. This should shape our confidence rules.

Implication for SuperContext:

- Use labels/selectors to infer deploy topology and service-to-workload mappings.
- Treat `app.kubernetes.io/name`, `app.kubernetes.io/instance`, `app.kubernetes.io/component`, `app.kubernetes.io/part-of`, and `app.kubernetes.io/version` as high-value identity hints.
- Do not treat arbitrary labels as authoritative global service identity.
- Use owner references to build deployable containment edges.

Sources:

- Kubernetes labels and selectors: https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/
- Kubernetes recommended labels: https://kubernetes.io/docs/concepts/overview/working-with-objects/common-labels
- Kubernetes well-known labels/annotations: https://kubernetes.io/docs/reference/labels-annotations-taints/
- Kubernetes owners/dependents: https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/
- Kubernetes annotations: https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations

### 8. CODEOWNERS

CODEOWNERS is useful for repo/path ownership but should not be confused with service ownership.

Useful concepts:

- path pattern
- owner user/team
- precedence rules
- review routing / ownership evidence

Important lesson:

CODEOWNERS proves code ownership or review responsibility, not necessarily business or runtime service ownership.

Implication for SuperContext:

- Model `owns` edges from owner/team to repo path or source file region.
- Promote to service ownership only when combined with service catalog metadata, repo layout conventions, or explicit service ownership files.
- Keep CODEOWNERS provenance at file/path precision.

Sources:

- GitHub CODEOWNERS docs: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners

### 9. W3C PROV

W3C PROV is useful for provenance semantics, but too heavy to adopt directly as the whole graph model.

Useful concepts:

- Entity: a thing/fact/artifact.
- Activity: the extraction, observation, indexing, or transformation process that produced a fact.
- Agent: person, system, or tool responsible for an activity or attributed entity.
- Relations: generated by, derived from, attributed to.

Important lesson:

Provenance should be a first-class model, not a string column. However, full semantic-web modeling would be overkill for Product 1.

Implication for SuperContext:

- Define a lightweight `EvidenceRecord` / `FactProvenance` shape inspired by PROV.
- Every fact should record source entity, extraction activity, extractor/tool version, observed/generated time, and source coordinates.
- Derived facts must explicitly point to the underlying facts they were derived from.

Sources:

- W3C PROV namespace: https://www.w3.org/ns/prov/
- W3C PROV overview: https://www.w3.org/TR/prov-overview/
- W3C PROV-DM: https://www.w3.org/TR/prov-dm/

### 10. CycloneDX

CycloneDX is useful for dependency graph discipline and completeness semantics.

Useful concepts:

- stable object references (`bom-ref`)
- components
- services
- dependency graph
- direct and transitive dependencies
- completeness/unknown dependency graph semantics

Important lesson:

CycloneDX explicitly distinguishes objects with known empty dependencies from objects not represented in the dependency graph. That is a critical distinction for SuperContext's refusal posture.

Implication for SuperContext:

- For v1 graph queries, represent coverage state explicitly:
  - known edge exists
  - known absent
  - unknown / uninstrumented
  - stale
- Do not answer "no callers" unless the relevant coverage is known complete enough for that claim.
- Use stable internal IDs inspired by `bom-ref` behavior: unique within graph scope, resolvable by all edges.

Sources:

- CycloneDX specification overview: https://cyclonedx.org/specification/overview
- CycloneDX service dependencies use case: https://cyclonedx.org/use-cases/service-dependencies/
- CycloneDX software dependencies use case: https://cyclonedx.org/use-cases/software-dependencies/

### 11. OpenLineage

OpenLineage is not a Product 1 core dependency, but it is good prior art for later platform expansion.

Useful concepts:

- `Job`
- `Run`
- `Dataset`
- input/output lineage
- facets as extensible metadata attached to core entities
- source-code-location and source-code-version metadata
- runtime events separate from design-time metadata events

Important lesson:

OpenLineage keeps a small core model and extends through facets. This is a useful pattern for the broader platform because it avoids exploding the canonical core ontology.

Implication for SuperContext:

- Use a small core fact model plus typed metadata/facets.
- For future docs/tickets/data/job expansion, avoid stuffing every source-specific field into core nodes.
- Separate runtime observations from design-time declarations.

Sources:

- OpenLineage object model: https://openlineage.io/docs/spec/object-model
- OpenLineage facets: https://openlineage.io/docs/1.28.0/guides/facets/
- OpenLineage GitHub overview: https://github.com/OpenLineage/OpenLineage

### 12. SCIP and LSIF

SCIP and LSIF are useful for future precise code intelligence, but should not define the Product 1 ontology.

Useful concepts:

- source document
- source range
- symbol occurrence
- definition/reference/implementation relationships
- language-agnostic index format
- symbol IDs

Important lesson:

SCIP exists because LSIF's graph encoding was complex. SCIP's human-readable symbol IDs and Protobuf schema are better inspiration if SuperContext later integrates code intelligence.

Implication for SuperContext:

- Product 1 should not require broad SCIP/LSIF indexing.
- The v1 ontology should leave room for future `Symbol`, `Occurrence`, `Definition`, and `Reference` facts.
- Evidence records should already support source ranges so future SCIP-like facts can attach cleanly.

Sources:

- SCIP repository: https://github.com/sourcegraph/scip/
- Sourcegraph SCIP announcement: https://sourcegraph.com/blog/announcing-scip
- Sourcegraph SCIP indexer docs: https://sourcegraph.com/docs/code-search/code-navigation/writing_an_indexer
- LSIF explanation: https://code.visualstudio.com/blogs/2019/02/19/lsif

---

## Suggested v1 ontology shape to evaluate next

This is a research-derived starting point, not a final decision.

### Likely v1 node types

- `Service`
- `Repo`
- `SourceFile`
- `Owner`
- `Api`
- `Endpoint`
- `Operation`
- `Schema`
- `EventChannel`
- `EventMessage`
- `Deployable`
- `RuntimeService`
- `Environment`

### Defer unless first design partner requires

- `Database`
- `FeatureFlag`
- `Incident`
- `Runbook`
- `Document`
- `Ticket`
- `CodeSymbol`
- `CodeOccurrence`

### Likely v1 relation types

- `ownedBy`
- `partOf`
- `definedIn`
- `implements`
- `providesApi`
- `consumesApi`
- `calls`
- `produces`
- `consumes`
- `deployedAs`
- `routesTo`
- `observedAs`
- `dependsOn`
- `derivedFrom`

### Relation semantics to keep separate

- `providesApi`: a service exposes an API contract.
- `consumesApi`: a service declares or is known to consume an API contract.
- `calls`: runtime or static evidence of invocation from one service/operation to another.
- `dependsOn`: broad operational dependency that may include deploy, resource, or library dependencies.
- `produces` / `consumes`: event/message relations.
- `definedIn`: artifact-to-source relation with coordinates.
- `derivedFrom`: fact-to-fact provenance relation.

Do not collapse these into one generic `depends_on` edge. The Product 1 tools need edge semantics precise enough to refuse safely.

---

## Metadata shape to define in the ADR

The ontology ADR should define one shared fact metadata envelope:

- `fact_id`
- `tenant_id`
- `entity_or_edge_type`
- `canonical_identity`
- `source_system`
- `source_ref`
- `source_coordinates`
- `extractor`
- `extractor_version`
- `ingested_at`
- `last_indexed_at`
- `last_observed_at`
- `valid_from`
- `valid_to`
- `confidence_class`
- `derivation_class`
- `coverage_state`
- `promotion_state`
- `evidence_refs`
- `acl_scope`

Recommended classes:

- `authoritative_declared`
- `deterministic_static`
- `runtime_observed`
- `manual_override`
- `candidate_llm`
- `candidate_inferred`
- `unknown_uninstrumented`
- `stale`

---

## Design rules for the v1 ontology ADR

1. Keep the canonical ontology small.
2. Borrow names where there is strong prior art.
3. Avoid source-specific names in canonical relation names unless the source is the domain concept.
4. Keep runtime observations separate from declared design facts.
5. Keep direct evidence separate from derived edges.
6. Model coverage explicitly; absence is not the same as unknown.
7. Make identities deterministic and source-coordinate-backed.
8. Allow future facets/metadata rather than expanding the core ontology for every platform use case.
9. Use candidate facts for uncertain aliases, inferred mappings, and prose-derived links.
10. Do not let GraphRAG-style relationships contaminate Product 1 operational answers.

---

## Main risks to avoid

- **Backstage overfit:** Backstage is excellent for catalog relations, but Product 1 also needs runtime and source-code evidence.
- **OTel overfit:** OTel span attributes are observation facts, not the canonical graph ontology.
- **Topic-name overfit:** Kafka topic names alone are insufficient; event/message/schema identity matters.
- **REST overfit:** GraphQL and gRPC do not map cleanly to REST endpoint semantics.
- **Code-indexer overfit:** SCIP/LSIF are powerful but too broad for v1 and already excluded from the evidence-retrieval v1 stack.
- **Semantic-web overfit:** W3C PROV is useful for provenance structure, not as the whole graph model.
- **False absence:** The graph must distinguish "no edge observed" from "coverage missing."

---

## Recommended next ADR

Create `ADR-0006: Define the Product 1 Canonical Ontology and Fact Metadata Envelope`.

That ADR should decide:

- final v1 node types
- final v1 relation types
- identity rules per node type
- required metadata envelope
- confidence / derivation / coverage classes
- candidate-to-canonical promotion states
- mappings from Backstage, OTel, OpenAPI, AsyncAPI, gRPC/protobuf, GraphQL, Kubernetes, and CODEOWNERS into canonical facts
- explicit out-of-v1 ontology items

