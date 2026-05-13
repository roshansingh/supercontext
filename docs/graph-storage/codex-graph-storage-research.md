# Graph Storage Research for SuperContext Product 1

> **✅ RESOLVED — 2026-04-29.** The final storage decision is captured in [`GRAPH-STORAGE-RECOMMENDATION.md`](./GRAPH-STORAGE-RECOMMENDATION.md) and [`../adr/0003-postgres-age-as-initial-graph-storage.md`](../adr/0003-postgres-age-as-initial-graph-storage.md). This note is preserved as research history and as a technical counterpoint considered during the decision. Its Neo4j recommendation is not the adopted project decision.

**Status:** Draft v0.1
**Date:** 2026-04-28
**Scope:** Choose the graph database for Product 1 based on the current MCP tools, likely future tools, and the graph model implied by the PRD.

---

## 1. Recommendation

Use **Neo4j** as the graph database for SuperContext Product 1.

More precisely:

- **Prototype / first design partner:** Neo4j Community Edition or AuraDB
- **Production SaaS / enterprise deployment:** Neo4j Enterprise or AuraDB
- **Fallback if fully-open-source self-hosting becomes a hard requirement:** reevaluate **Memgraph**

This is the best fit for the current MCP surface because Product 1 needs:

- labeled property graph modeling
- expressive multi-hop traversal queries
- shortest path / reachability / DAG-style dependency logic
- rich relationship properties for provenance, freshness, volume, and confidence
- good indexing options for service lookup and future semantic aliasing
- a query language that both engineers and LLMs can generate reliably

The graph database is not the moat by itself. The moat is the graph model and ingestion. But the database should make the MCP queries straightforward rather than awkward.

---

## 2. Why Neo4j

### 2.1 Best fit for the current MCP tools

The current Product 1 tools in [`PRD.md`](../PRD.md) imply a graph workload that is mostly:

- neighborhood queries
- inbound/outbound traversal
- bounded multi-hop impact expansion
- path-finding across deployment dependencies
- typed edge filtering
- ranking / summarization over graph neighborhoods

Neo4j fits that directly.

Relevant official capabilities:

- **Variable-length path patterns** in Cypher for traversing unknown or bounded path depth  
  Source: https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-patterns/
- **Shortest path support** in Cypher via `SHORTEST`  
  Source: https://neo4j.com/docs/cypher-manual/current/patterns/shortest-paths
- **Full-text indexes** on nodes and relationships  
  Source: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
- **Vector indexes** on nodes and relationships  
  Source: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- **Graph Data Science pathfinding and DAG algorithms** such as Dijkstra and Topological Sort  
  Sources:  
  https://neo4j.com/docs/graph-data-science/current/algorithms/pathfinding/  
  https://neo4j.com/docs/graph-data-science/current/algorithms/dag/topological-sort/

### 2.2 Best fit for future MCP tools

Even if the MVP only has 8 tools, likely future tools will need:

- rollout sequencing
- cycle detection in deploy blockers
- impact memo generation
- dependency ranking
- “why is this service risky?” style graph analysis
- incident neighborhood expansion
- migration campaign planning

Neo4j’s Cypher plus GDS covers these better than a thinner graph layer.

### 2.3 Best MCP and agent ecosystem

Neo4j already has an **official MCP server** with read-only mode, query classification, schema sampling, and optional Graph Data Science integration.

Source: https://github.com/neo4j/mcp

That does **not** mean we should expose the raw database directly as the user-facing SuperContext MCP. We should still build our own narrow MCP surface.

But it is a strong signal that:

- Neo4j already fits MCP usage patterns
- tooling around agent access is mature
- internal debugging / admin workflows will be easier

### 2.4 Cypher is the right query language for this product

This matters more than it sounds.

For Product 1, we will eventually have:

- humans writing diagnostic queries
- internal services generating queries
- agents producing or validating graph queries

Cypher is a better fit than Gremlin or a lower-level traversal API for this workflow. It is declarative, graph-native, and already widely used in the graph ecosystem.

This is also one reason I prefer Neo4j over Neptune for this product.

---

## 3. Why not the main alternatives

## 3.1 Memgraph

**Verdict:** strong runner-up, not first choice.

Why it is attractive:

- uses Cypher
- supports ACID transactions and persistence
- has built-in graph algorithms
- has stream connectors and triggers
- has an MCP server

Sources:

- https://memgraph.com/capabilities
- https://memgraph.com/memgraphdb/
- https://memgraph.com/blog/introducing-memgraph-mcp-server

Why I am not choosing it first:

- its MCP server is still much thinner; the public announcement currently describes essentially a `run_query()` bridge
- the ecosystem around tooling, query examples, operations, and graph/LLM integration is still weaker than Neo4j’s
- for this product, the biggest risk is not raw traversal speed; it is correctness, modeling ergonomics, and ecosystem maturity

If we later optimize for:

- streaming graph updates as the center of the product
- fully-open-source self-hosting
- tighter trigger/stream behavior inside the database

then Memgraph deserves a second look.

## 3.2 Amazon Neptune

**Verdict:** not a fit for Product 1 as the primary graph store.

Why:

- openCypher support has important limitations
- `shortestPath()` and `allShortestPaths()` are not supported in Neptune openCypher
- `CALL` is not supported in Neptune openCypher
- full-text search requires an external OpenSearch integration

Sources:

- https://docs.aws.amazon.com/neptune/latest/userguide/feature-opencypher-compliance.html
- https://docs.aws.amazon.com/neptune/latest/userguide/full-text-search.html

Neptune is strong if:

- you are already fully inside AWS
- managed infrastructure is the top priority
- you can live within Neptune’s query model and operational choices

But Product 1 needs a more ergonomic graph developer experience than Neptune provides.

## 3.3 Apache AGE / AgensGraph

**Verdict:** interesting hybrid option, not the best choice here.

Why it is attractive:

- graph functionality inside PostgreSQL
- SQL + openCypher hybrid queries
- ACID and Postgres ecosystem reuse

Sources:

- https://age.apache.org/overview/
- https://www.postgresql.org/about/news/announcing-the-release-of-agensgraph-v2150-3058/

Why I am not choosing it:

- Product 1’s core difficulty is graph traversal and graph reasoning, not relational coexistence
- the graph ecosystem, MCP story, and graph-native tooling are weaker than Neo4j’s
- if we want a dedicated graph database, we should choose one that is clearly graph-first

If we instead decide we do **not** want a dedicated graph database yet, then a Postgres-centered design becomes a separate discussion. But that is different from the current request.

## 3.4 ArangoDB

**Verdict:** capable, but not the best fit.

ArangoDB has good traversal support through AQL and named graphs.

Source: https://docs.arangodb.com/3.11/aql/graphs/traversals/

But for Product 1:

- AQL is less natural for graph-specific agent-generated queries than Cypher
- the graph/agent/MCP ecosystem is weaker
- it is more multi-model than we currently need

---

## 4. What the MCP tools imply about the graph shape

The current MCP tools do not imply a generic “knowledge graph.” They imply a very specific **typed operational dependency graph**.

### `search_services`

Needs:

- indexed lookup by service name, alias, owner, tag, repo, domain
- eventually semantic aliasing on descriptions and docs

Graph implication:

- strong indexed `Service` nodes
- `Team`, `Repo`, and tag-like metadata

### `get_service_brief`

Needs:

- one-hop neighborhood summary
- key upstream and downstream services
- owned endpoints and topics
- deploy environment and ownership context

Graph implication:

- direct edges from `Service` to `Endpoint`, `EventTopic`, `Repo`, `Team`, `Deployable`
- precomputable or easily traversable local neighborhood

### `find_callers`

Needs:

- inbound traversal from an endpoint or method
- parser strictness and traffic metadata
- source provenance

Graph implication:

- endpoint-level graph, not just service-level graph
- `CALLS` edges need properties like `protocol`, `traffic_volume`, `strictness`, `confidence`, `last_seen_at`

### `find_callees`

Needs:

- outbound traversal from service or endpoint
- version / protocol metadata

Graph implication:

- same as `find_callers`, but strongly argues for both:
  - `Service -> Endpoint`
  - `Endpoint -> Endpoint`
  - optional derived `Service -> Service`

### `get_event_consumers` / `get_event_producers`

Needs:

- event topics and subjects
- schema version awareness
- last-seen / last-produced data

Graph implication:

- event graph is first-class
- `EventTopic` and `SchemaVersion` should be nodes, not just properties

### `blast_radius`

Needs:

- multi-hop traversal from changed contracts, endpoints, events, or deploy units
- path expansion with pruning
- ranking and explanation
- refusal when graph coverage is insufficient

Graph implication:

- typed paths matter
- provenance and confidence must be stored with relations
- graph should support path queries without awkward workarounds

### `deploy_blockers_for`

Needs:

- dependency sequencing
- DAG-like traversal
- cycle detection
- future topological sort / rollout planning

Graph implication:

- explicit deploy dependency edges
- future use of DAG and path algorithms

---

## 5. Recommended graph model

The right graph model is a **labeled property graph**, not RDF.

Why:

- entities are heterogeneous and evolving
- relationships carry important metadata
- edge properties are central, not incidental
- Cypher query ergonomics matter

This is an inference from the tool requirements and the PRD’s graph shape, not a quote from any one source.

### 5.1 Core node types for Product 1

- `Service`
- `Endpoint`
- `Operation`
- `EventTopic`
- `SchemaVersion`
- `Deployable`
- `Deployment`
- `Repo`
- `Team`
- `Person`
- `Environment`
- `Cluster`
- `Namespace`

### 5.2 Future node types we should leave room for

- `FeatureFlag`
- `Database`
- `Runbook`
- `Incident`
- `ADR`
- `Ticket`
- `Document`

The broader platform will likely add more, but these are the obvious next ones from the current roadmap.

### 5.3 Core relationship types for Product 1

- `(:Service)-[:OWNS_ENDPOINT]->(:Endpoint)`
- `(:Endpoint)-[:IMPLEMENTS]->(:Operation)`
- `(:Operation)-[:USES_SCHEMA]->(:SchemaVersion)`
- `(:Endpoint)-[:CALLS]->(:Endpoint)`
- `(:Service)-[:CALLS_SERVICE]->(:Service)`  
  Derived convenience edge, not the only source of truth
- `(:Service)-[:PRODUCES]->(:EventTopic)`
- `(:Service)-[:CONSUMES]->(:EventTopic)`
- `(:EventTopic)-[:CURRENT_SCHEMA]->(:SchemaVersion)`
- `(:SchemaVersion)-[:EVOLVES_TO]->(:SchemaVersion)`
- `(:Service)-[:OWNED_BY]->(:Team)`
- `(:Team)-[:HAS_MEMBER]->(:Person)`
- `(:Service)-[:DEFINED_IN]->(:Repo)`
- `(:Deployable)-[:FOR_SERVICE]->(:Service)`
- `(:Deployable)-[:DEPLOYS_TO]->(:Environment)`
- `(:Deployment)-[:OF_DEPLOYABLE]->(:Deployable)`
- `(:Deployment)-[:ROLLED_OUT_TO]->(:Cluster)`

### 5.4 Near-term future relationships

- `(:Service)-[:GATED_BY]->(:FeatureFlag)`
- `(:Deployable)-[:DEPLOY_BLOCKED_BY]->(:Deployable)`
- `(:Service)-[:SHARES_DB_WITH]->(:Service)`
- `(:Service)-[:MIGRATES_WITH]->(:Service)`
- `(:Incident)-[:IMPACTED]->(:Service)`
- `(:Runbook)-[:DOCUMENTS]->(:Service)`

---

## 6. Relationship properties the graph must support

This is one of the main reasons we need a property graph.

At minimum, important operational edges need properties like:

- `fact_id`
- `source_types`  
  Example: `["static", "trace", "manifest"]`
- `confidence`
- `first_seen_at`
- `last_seen_at`
- `last_indexed_at`
- `environment_scope`
- `protocol`
- `traffic_volume`
- `strictness`
- `version`
- `is_deprecated`

Example:

`(:Endpoint)-[:CALLS {protocol:"grpc", confidence:0.98, traffic_volume:128394, strictness:"strict", last_seen_at:"2026-04-28T11:20:00Z"}]->(:Endpoint)`

That edge shape is much more natural in Neo4j than in systems where graph traversal is secondary.

---

## 7. Provenance model recommendation

The graph should have **two layers**:

### Layer A: canonical traversal graph

Fast direct relationships for the MCP tools.

Example:

- `CALLS`
- `PRODUCES`
- `CONSUMES`
- `DEPLOY_BLOCKED_BY`

These edges should include summary properties like confidence, timestamps, and high-level provenance summary.

### Layer B: supporting evidence graph

Detailed evidence records for citations and debugging.

Suggested node types:

- `Evidence`
- `SourceFile`
- `TraceObservation`
- `Manifest`
- `SchemaRegistryRecord`

Suggested relationships:

- `(:Evidence)-[:SUPPORTS]->(:Service)` only when node-level support is needed
- `(:Evidence)-[:SUPPORTS_FACT {fact_id: "..."}]->(:EvidenceAnchor)`

Practical recommendation:

- keep the canonical operational graph in Neo4j
- attach evidence by stable `fact_id`
- do **not** force every traversal query to walk through evidence nodes

This keeps the MCP tools fast while preserving auditability.

---

## 8. Why Neo4j is the best fit for this model

Neo4j matches the graph shape above well because:

- relationships are first-class and can carry rich properties
- Cypher handles variable-length traversal clearly
- full-text and vector indexes are available inside the same database
- GDS gives us a credible path for future pathfinding, ranking, and DAG workflows
- MCP support already exists officially

This combination matters more than any one feature in isolation.

---

## 9. Deployment recommendation

### V1

Use one of:

- **AuraDB** if we want managed infrastructure fast
- **Neo4j Community Edition** if we want the fastest local/dev loop

### Production / multi-tenant SaaS

Use:

- **Neo4j Enterprise** or **AuraDB**

Reason:

- clustering, failover, and stronger production operations are enterprise concerns in Neo4j’s model  
  Source: https://neo4j.com/docs/operations-manual/current/introduction/

### Self-hosted enterprise customers

Use:

- **Neo4j Enterprise**

If license posture becomes a blocker for target customers, the most plausible alternative to revisit is **Memgraph**, not Neptune.

---

## 10. Final conclusion

If we are choosing a **dedicated graph database** for Product 1, the best choice is **Neo4j**.

Why:

- best match for the current MCP tool queries
- best Cypher ergonomics
- strongest graph + agent ecosystem
- strong path to future graph analytics
- direct support for the typed, edge-heavy operational graph we need

The graph SuperContext needs is not a generic knowledge graph. It is a typed operational dependency graph with rich relationship properties, provenance, and future pathfinding needs.

Neo4j is the clearest fit for that shape.

---

## 11. Sources

- SuperContext Product 1 PRD  
  [`PRD.md`](../PRD.md)
- Neo4j Cypher Manual: Variable-length patterns  
  https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-patterns/
- Neo4j Cypher Manual: Shortest paths  
  https://neo4j.com/docs/cypher-manual/current/patterns/shortest-paths
- Neo4j Cypher Manual: Full-text indexes  
  https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
- Neo4j Cypher Manual: Vector indexes  
  https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Neo4j Operations Manual  
  https://neo4j.com/docs/operations-manual/current/introduction/
- Neo4j Graph Data Science: Path finding  
  https://neo4j.com/docs/graph-data-science/current/algorithms/pathfinding/
- Neo4j Graph Data Science: Topological Sort  
  https://neo4j.com/docs/graph-data-science/current/algorithms/dag/topological-sort/
- Neo4j official MCP server  
  https://github.com/neo4j/mcp
- Memgraph capabilities  
  https://memgraph.com/capabilities
- Memgraph database overview  
  https://memgraph.com/memgraphdb/
- Memgraph MCP server announcement  
  https://memgraph.com/blog/introducing-memgraph-mcp-server
- Amazon Neptune openCypher access  
  https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html
- Amazon Neptune openCypher compliance  
  https://docs.aws.amazon.com/neptune/latest/userguide/feature-opencypher-compliance.html
- Amazon Neptune full-text search  
  https://docs.aws.amazon.com/neptune/latest/userguide/full-text-search.html
- Apache AGE overview  
  https://age.apache.org/overview/
- AgensGraph release note  
  https://www.postgresql.org/about/news/announcing-the-release-of-agensgraph-v2150-3058/
- ArangoDB graph traversals  
  https://docs.arangodb.com/3.11/aql/graphs/traversals/
