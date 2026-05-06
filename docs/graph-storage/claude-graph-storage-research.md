# Graph Storage Research — SuperContext Product 1

> **✅ RESOLVED — 2026-04-29.** The binding decision now lives in [`GRAPH-STORAGE-RECOMMENDATION.md`](./GRAPH-STORAGE-RECOMMENDATION.md) and [`../adr/0003-postgres-age-as-initial-graph-storage.md`](../adr/0003-postgres-age-as-initial-graph-storage.md). This document is preserved as a research input that supported the final decision; do not treat it as the final authority.

- **Status:** Recommendation
- **Date:** 2026-04-28
- **Authors:** Roshan Singh, Maruti Agarwal
- **Anchors:** `PRD.md` §6.1 (engine), §6.2 (MCP tools), §8 (architecture), `PLATFORM-PRD.md` §8 (broader entity types for Phase 2/3)

---

## 1. TL;DR

**Recommendation: Apache AGE on PostgreSQL 16/17.** A single Postgres instance, an Apache 2 graph extension that gives us openCypher syntax against vertex/edge tables, and the entire surrounding Postgres ecosystem the team already knows (psql, pgbench, pg_dump, CDC, Patroni, RDS-class operability, Helm charts that already exist). Multi-tenant isolation falls out for free — every AGE graph lives in its own Postgres schema, so per-tenant graphs are just per-tenant `CREATE GRAPH`s. License is unambiguous Apache 2 on both AGE and Postgres. Active: v1.7.0 released **Jan 21, 2026** with PG 18 support.

**Runner-up: Dgraph v25 (Apache 2 since Feb 2025, latest v25.3.3 April 2026).** A native distributed graph engine, no longer encumbered by Hypermode's pivot — Istari Digital acquired in Oct 2025 and committed to OSS/self-host. Stronger pure-graph performance ceiling than AGE, but new ownership is a one-quarter risk and the Helm/operability story is heavier than "another Postgres."

This is **a Postgres play with a graph extension on top, not a native graph DB play**. PRD.md §8 already says "Postgres + graph index" — this research confirms the instinct rather than overruling it.

---

## 2. Query patterns analyzed

The 8 MCP tools (PRD.md §6.2) plus likely Phase-2 tools drive the read patterns.

| MCP tool | Query shape | Hardness |
|---|---|---|
| `search_services` | Full-text + property lookup over Service nodes | Trivial — Postgres GIN/trigram |
| `get_service_brief` | 1-hop neighborhood, depth=1, ~10–50 nodes returned | Easy — single Cypher MATCH or two SQL joins |
| `find_callers` / `find_callees` | 1-hop edge traversal on Endpoint with property filter (parser_strictness, traffic_volume, last_seen_at) | Easy — indexed edge scan |
| `get_event_consumers` / `get_event_producers` | 1-hop on Event/Topic, filter by `last_seen_at >= now()-30d` | Easy — temporal property filter |
| `blast_radius` | **Variable-depth traversal** (typically 2–4 hops) from a diff's touched Endpoints/Schemas → all downstream consumers, joined with parser_strictness + last_seen_at | **Hardest tool.** Recursive traversal with property filtering at each step |
| `deploy_blockers_for` | Topological / dependency-order traversal over `migrates_with` and `depends_on` edges | Hard — recursive + ordering |
| `find_consumers_of_field` (future) | Schema-version-aware: which consumers parse field `X` at any non-deprecated version | Multi-hop with temporal join |
| `oncall_context_for` (future) | Diff call graph "now" against call graph "1h ago" — set difference on edges with observed_at windows | Temporal + bitemporal-ish |
| `auth_fan_out` (future) | Multi-hop reachability from a claim definition to every reading service | Recursive |
| `historical_incidents_near` (future) | Cross-entity multi-hop (Code → Service → Incident) | Multi-hop with mixed types |

**Hot path:** `blast_radius` and `deploy_blockers_for` are the SLA-defining queries. Worst case: starting Service touches 1 Endpoint → 50 callers → each with ~10 callers → 5,000-node frontier. Depth ≤ 4 dominates. With proper indexes on `(source_node_id)` and `(target_node_id, edge_type)` this is bounded sub-second on any modern engine.

**Workload shape:** read-heavy, batch writes from ingestion workers, single-tenant per query — exactly what Postgres has been tuned for over 30 years.

---

## 3. Candidate landscape

### Native graph databases

**Neo4j Community.** Cypher; **GPLv3** (Community) or proprietary (Enterprise); JVM single-node (no clustering in Community); mature property model. **Verdict: wrong fit.** GPLv3 plus Enterprise-only clustering means we either accept GPL viral ambiguity for our own code or buy Enterprise the moment we want HA. Neither survives a regulated-buyer Helm review.

**Memgraph.** Cypher-compatible; **BSL 1.1** with an Additional Use Grant that explicitly forbids "database-as-a-service or equivalent distributed model." Change date March 25, 2030 → Apache 2. Latest v3.9.0 (Mar 2026). Very alive. **Verdict: license-blocked.** Our SaaS plane is exactly the prohibited use case.

**Apache AGE.** openCypher + SQL on Postgres; **Apache 2.0**; runs anywhere Postgres runs; per-graph Postgres schema gives clean multi-tenancy; **v1.7.0 Jan 21, 2026** with PG 18. Edge-creation has a known performance gotcha at large bulk loads (workaround: insert directly to underlying tables, ~1000× speedup), but this is an ingestion concern, not a read-path concern. **Verdict: top fit.**

**KuzuDB.** Cypher; MIT; embedded. **Verdict: dead.** Repo archived Oct 10, 2025. Skip.

**FalkorDB.** Cypher on Redis modules; **SSPL**. Active (v4.18.2 April 2026). **Verdict: license risk.** SSPL forces source disclosure of "all management software, UIs, APIs, monitoring, hosting" if we expose FalkorDB-as-a-service. Not OSI-recognized; legal review tax.

**ArangoDB.** AQL; multi-model went **BSL 1.1 starting v3.12** (formerly Apache 2), with a Community License binary capping single-cluster datasets at 100 GB. **Verdict: license regression** plus unclear resale.

**Dgraph.** GraphQL+/-; **Apache 2 (full codebase since v25, ~Feb 2025)**; distributed; Istari Digital acquired Oct 2025 and committed to "open-source and self-hosted." Latest v25.3.3 (April 21, 2026). **Verdict: alive, license-clean, runner-up.** Ownership transfer is the one yellow flag.

**JanusGraph.** Gremlin/TinkerPop; Apache 2; Cassandra/HBase. Latest official v1.1.0 **Nov 9, 2024** — no 2025 official releases. **Verdict: limping.** Gremlin is a worse fit for AI agents than Cypher (more verbose, less LLM training data); Cassandra dependency is a heavy ops burden; cadence is slowing.

**NebulaGraph.** nGQL + openCypher subset; Apache 2; distributed. No clear 2025–2026 cadence on the core repo. **Verdict: cadence concern.** Strong scale story (Tencent, Meituan internal) but no recent verifiable stable release.

**TerminusDB.** WOQL + GraphQL; Apache 2; immutable git-for-data; Prolog-derived engine. v12 (Mar/Dec 2025), maintainership transferred to DFRNT in 2025. **Verdict: interesting but niche.** Immutable history matches our provenance need beautifully, but Prolog/Rust runtime + custom WOQL + fresh maintainer transition = exotic for Phase 1. Park as Phase-3 reconsideration.

**TigerGraph / AWS Neptune.** Commercial-only / managed-only. Skip.

**Cayley.** Last release v0.7.7 October 2019. Skip (dead).

### Datalog / fact stores

**Glean (Meta).** BSD; Haskell; designed for code facts (literally our use case). No formal releases — "pre-release software, rough edges, limited language indexers." **Verdict: aspirational, not operable.** Asking customers to run a Haskell binary in production is a non-starter for the regulated-buyer ICP, and we'd be the world's #2 production Glean operator after Meta. Not the role for Phase 1.

**Datomic.** Apache 2 since April 2023 (Nubank). Mature, bitemporal, beautiful provenance model. **Verdict: alive but JVM-heavy.** Operational model (separate transactor, Cassandra/DynamoDB/Postgres for storage) is a heavier Helm chart than AGE.

**XTDB v2.** **MPL 2.0**; v2.0 GA June 2024, v2.1.0 Dec 2024; XTQL (Datalog-derived) + SQL; **bitemporal out of the box**. **Verdict: strong dark-horse for provenance/temporal needs.** MPL is fine for resale. Bitemporal model maps cleanly onto our `last_seen_at`/`observed_at` requirement. JVM but a single binary. Worth a prototype as the "ingestion-truth" store even if AGE serves the read path.

**Datalevin.** EPL 1.0; embedded Clojure Datalog over LMDB. **Verdict: too embedded.** Single-process design fights SaaS multi-tenancy; we'd be the only shop running Clojure in production.

**TypeDB.** AGPL or commercial; v3.0 Dec 2024 (Rust rewrite). **Verdict: AGPL is a non-starter for resale-as-Helm.**

### Relational + graph extensions

**Postgres + Apache AGE.** Already covered. Top recommendation.

**Postgres + recursive CTEs (no AGE).** Apache 2 / PostgreSQL license. Works. Slightly more verbose for blast_radius queries; no openCypher. **Verdict: viable, sub-optimal.** AGE saves us from hand-rolling a Cypher-ish DSL.

**DuckDB-PGQ.** MIT; SQL/PGQ standard (SQL:2023); embedded; in-process. **Verdict: wrong shape.** Analytical engine, not transactional; embedded → no concurrent write/read in an ingestion+serving deployment. Excellent for batch graph analytics jobs (Phase 3 offline analyzer).

**SurrealDB.** SurrealQL; **BSL 1.1**, Additional Use Grant permits everything except DBaaS resale; Apache 2 four years post-release; v3.0 GA. **Verdict: probably acceptable license-wise** (we're not a DBaaS), but positioning is promiscuous (document + graph + time-series + KV) and production track record is thinner than Postgres'. Multi-tenant story less crisp than AGE's per-graph-per-namespace.

### RDF / SPARQL

**Apache Jena Fuseki.** Apache 2; JVM. RDF is a heavier modeling tax than property-graph for our use case (every property → reified triples or RDF-star). Skip for primary store.

**Blazegraph.** Frozen since 2020-ish. Skip.

**Stardog.** Commercial. Skip.

**Oxigraph.** Apache 2; Rust; SPARQL 1.1+1.2/RDF 1.2; v0.5.3 Dec 19, 2025. **Verdict: alive and lightweight**, but same RDF-modeling-tax issue. Rule out for primary store.

---

## 4. Scoring matrix

Columns: **Prov** (provenance per fact), **Temp** (versioning/temporal), **MT** (multi-tenant), **Helm** (self-hosted ergonomics), **Read** (read latency for blast_radius), **Lic** (license sanity for resale), **Ops** (operability), **Eco** (ecosystem health).

| Candidate | Prov | Temp | MT | Helm | Read | Lic | Ops | Eco |
|---|---|---|---|---|---|---|---|---|
| **Apache AGE on Postgres** | ✓ properties on edges/nodes | ⚠ no native bitemporal, model `valid_from/valid_to` | ✓ per-graph schema isolation | ✓ best in class — Postgres Helm is solved | ✓ sub-second 4-hop on 100k edges with proper indexes | ✓ Apache 2 + Postgres license | ✓ Postgres ops are commodity | ✓ ASF + Microsoft (Azure PG) backing |
| **Dgraph v25** | ✓ facets on edges (provenance fits) | ⚠ no bitemporal; properties only | ✓ namespaces feature | ⚠ distributed runtime, multiple binaries | ✓ designed for this | ✓ Apache 2 (all of v25) | ⚠ Zero/Alpha topology + acquisition uncertainty | ⚠ Istari just took ownership Oct 2025 |
| **XTDB v2** | ✓ documents are facts; native | ✓ bitemporal native (best in class) | ⚠ no first-class tenant isolation | ⚠ JVM single binary, separate object store | ✓ columnar, designed for analytical hops | ✓ MPL 2.0 | ⚠ JVM + Arrow + S3-class object store | ⚠ JUXT-shop, smaller community |
| **SurrealDB** | ✓ schemaless properties | ⚠ no native temporal | ⚠ namespaces exist, less battle-tested | ✓ single Rust binary | ⚠ less mature traversal optimizer than AGE/Dgraph | ⚠ BSL (DBaaS-only restriction; OK for us) | ✓ single binary | ⚠ younger product, churning |
| **Postgres + recursive CTEs (no AGE)** | ✓ ordinary columns | ⚠ same as AGE | ✓ schema-per-tenant | ✓ best in class | ⚠ sub-second possible but verbose; we hand-roll the DSL | ✓ PostgreSQL license | ✓ ops are commodity | ✓ Postgres community |
| **Memgraph** | ✓ properties | ⚠ no bitemporal | ✓ multi-tenant feature | ✓ single C++ binary | ✓ in-memory, very fast | ✗ **BSL forbids SaaS resale** | ✓ single binary | ✓ active, well-funded |
| **Neo4j Community** | ✓ properties | ⚠ no bitemporal | ⚠ separate DBs only in Enterprise | ⚠ JVM single node (no HA Community) | ✓ proven | ✗ **GPLv3 viral concern** | ⚠ JVM | ✓ market leader |

Reading the matrix: **AGE wins on every column except temporal**, and that we mitigate by modeling `valid_from`/`valid_to` columns on edges — the same approach we'd take in any non-bitemporal store.

---

## 5. Recommendation

**Phase 1: Apache AGE on PostgreSQL 16, Apache 2.**

Why this combo over the alternatives a reviewer will challenge:

- **Why not Neo4j Community?** GPLv3. Even setting aside the unsettled viral debate, Enterprise-only clustering means HA = commercial Neo4j contract or storage migration. Neither survives the regulated-buyer ICP review.

- **Why not Glean?** Beautiful model match (literally a code-facts store), but no formal releases, "pre-release software," Haskell. Operating Glean for a self-hosted regulated customer means we are the world's #2 production Glean operator after Meta. Revisit when they publish a 1.0.

- **Why not just Postgres (no AGE)?** Tempting — same Helm chart. But blast_radius queries become 60-line recursive CTEs, and we'd be reinventing the openCypher-to-SQL compiler that AGE already gives us. Cost of *adding* AGE = one `CREATE EXTENSION age` line; cost of *removing* it later = one line. Take the win.

- **Why not Dgraph?** It's the runner-up. Native graph engine, Apache 2, distributed scale headroom we may never need. Held back by (a) ownership transfer Oct 2025 — one quarter to confirm Istari's roadmap holds — and (b) running Dgraph means running Zero + Alpha cluster, more Helm than `helm install postgres`. Pick Dgraph if AGE limits hit at a 500-service customer.

- **Why not XTDB?** Stronger temporal/bitemporal model than AGE. But JVM + Arrow + object-store dependency makes the Helm chart heavier, and our temporal needs are well-served by `valid_from`/`valid_to` columns on edges. Park as Phase-3 reconsideration if `oncall_context_for(since=1h)` and similar bitemporal queries become hot.

**Fallback / migration path:** If AGE's edge-write throughput chokes ingestion at a 500-service customer (the documented edge-creation perf issue), two roads: (a) the documented direct-table-insert workaround (~1000× speedup), or (b) lift-and-shift to Dgraph keeping the same Cypher-ish query layer (Dgraph supports DQL/GraphQL+/-, not Cypher, so we'd also write a query translator — non-trivial but bounded).

---

## 6. Schema design (on Apache AGE)

Multi-tenancy: **one PostgreSQL database per region, one AGE graph per tenant** (`SELECT * FROM cypher('tenant_acme', $$ ... $$);`). AGE creates a Postgres schema per graph, so `pg_dump --schema=tenant_acme` is a per-tenant export and Row-Level Security is unnecessary at the graph layer. Self-hosted = single tenant = one graph.

### Node types and properties

```
(:Service {
   id, name, slug, repo_url, primary_language, owner_team_id,
   tier, created_at, last_indexed_at,
   provenance_jsonb         -- {commit_sha, file, line, source_system}
})
(:Endpoint {
   id, service_id, method, path, protocol,        -- 'rest' | 'grpc' | 'graphql'
   schema_id, schema_version,
   parser_strictness,                              -- 'strict' | 'lenient' | 'unknown'
   provenance_jsonb, last_indexed_at
})
(:Schema {
   id, name, version, format,                      -- 'openapi' | 'proto' | 'avro' | 'json-schema'
   content_hash, fields_jsonb,
   provenance_jsonb, last_indexed_at
})
(:Event { id, topic, schema_id, schema_version, provenance_jsonb, last_indexed_at })
(:Deploy { id, service_id, version, env, deployed_at, deployed_by, provenance_jsonb })
(:Repo { id, url, default_branch, last_indexed_at })
(:Owner { id, kind, name, slack, email })          -- kind: 'team' | 'person'
(:Database { id, kind, name, provenance_jsonb })
(:FeatureFlag { id, key, default_value, provenance_jsonb })
```

### Edge types and properties

```
(:Service)-[:CALLS {
   confidence,               -- 0.0–1.0
   evidence,                 -- 'static' | 'trace' | 'manifest'
   traffic_volume_per_day,   -- nullable until trace ingestion fires
   first_observed_at, last_observed_at,
   provenance_jsonb,
   valid_from, valid_to      -- temporal window
}]->(:Endpoint)

(:Service)-[:PRODUCES {schema_version, last_observed_at, provenance_jsonb}]->(:Event)
(:Service)-[:CONSUMES {schema_version, parser_strictness, last_observed_at, provenance_jsonb}]->(:Event)
(:Owner)-[:OWNS {since, provenance_jsonb}]->(:Service)
(:FeatureFlag)-[:GATES {provenance_jsonb}]->(:Service)
(:Deploy)-[:MIGRATES_WITH {ordering, provenance_jsonb}]->(:Deploy)
(:Service)-[:SHARES_DB_WITH {connection_string_hash, provenance_jsonb}]->(:Database)
```

### Where provenance lives

**On the edge for relational facts; on the node for entity facts; on a separate `:Fact` node only when one fact has multiple sources.** Trade-off: putting it on the edge means a single row per fact (best for read perf), and AGE's properties are JSONB, so a `provenance_jsonb` column is cheap. A separate Fact node would make multi-source reconciliation cleaner but doubles the join count on every blast_radius — not worth it.

The day a single edge needs to come from two sources (e.g., a `CALLS` edge proven by both static analysis *and* a Datadog trace), we promote that edge to a Fact node. Everything else stays inline.

### Versioning

- **Schema versions** are first-class `:Schema` nodes (not properties). `(s1:Schema)-[:SUPERSEDES]->(s2:Schema)`.
- **Edge `valid_from`/`valid_to` columns** make every edge temporal-by-construction. `last_observed_at` is the trace-derived freshness. Soft-delete is `valid_to = now()`; we never hard-delete (auditability).
- A nightly job fires a stale-edge pass: any edge whose `last_observed_at < now() - 30d` for trace-evidence edges gets `valid_to` set, freeing the next ingestion to write a successor.

### Tenant isolation pattern

- **SaaS plane:** one Postgres database per region, one AGE graph per tenant (Postgres schema isolation via AGE's namespace model). Connection-pooler routing by tenant_id.
- **Self-hosted Helm release:** one Postgres + one AGE graph. Tenant isolation collapses to "one Helm release per customer" — what the regulated-buyer ICP wants anyway.

Multi-tenancy is **a property of the connection string, not a `WHERE tenant_id = ?` predicate** — big risk-reduction.

---

## 7. Migration to Phase 2/3

The schema above absorbs Phase 2/3 entities with **zero rewrite, only additive `CREATE VLABEL` calls**:

- New nodes (`:Document`, `:Ticket`, `:Decision`, `:Runbook`, `:Incident`, `:File`, `:Person`, `:Team`) get labels and properties; AGE adds them as new tables under the same graph schema.
- New edges (`:DOCUMENTS`, `:MENTIONS`, `:RELATES_TO`, `:BLOCKS`, `:PLANNED_BY`, `:RESOLVED_BY`) plug into existing nodes via `MATCH ... CREATE` with no schema migration.
- The provenance JSONB blob extends to source systems we don't yet know (Confluence, Jira, OneDrive) without migration — just new keys.

The smallest change at the Phase 2 boundary is **`:Owner` → `:Person`/`:Team` reconciliation** in ingestion (today's Owner is a stand-in; once we ingest Slack/IDP we promote it to a typed `:Person` with `(:Person)-[:MEMBER_OF]->(:Team)-[:OWNS]->(:Service)`). One ingestion job, no schema change.

The Phase-3 risk is **cross-graph queries** ("incidents related to this PR's blast radius"). AGE handles this natively because all node types live in the same graph; the only thing we must avoid is splitting Phase 1 entities into one graph and Phase 2 entities into another. **Keep one graph per tenant, always.**

---

## 8. Open questions

1. **AGE bulk-edge-insert performance.** The known issue (83k edges in ~1h via Cypher; ~1000× speedup via direct table inserts) — does this hit our ingestion SLAs at 100k+ edges per tenant? *Validate: load a fixture of 500 services × 5,000 endpoints × 100,000 call edges, measure ingestion wall-clock.* (apache/age#1925)
2. **AGE 4-hop blast_radius latency.** Does it hit p95 < 500 ms with proper indexing on the 100k-edge fixture? *Validate: EXPLAIN ANALYZE on the actual blast_radius Cypher with realistic neighborhood fan-out.*
3. **Cypher coverage.** AGE implements openCypher but has gaps vs Neo4j. Does our 8-tool query set fit AGE's subset? *Validate: write all 8 queries against a toy graph.*
4. **AGE upgrade story.** Can we run a `helm upgrade` from AGE 1.5 → 1.7 without a reindex? Does PG 18 + AGE 1.7 work in production yet, or do we pin to PG 17?
5. **Dgraph ownership stability.** Is Istari Digital's Dgraph commitment surviving past Q3 2026? Worth a check before we commit to the fallback.
6. **Bitemporal modeling overhead.** `valid_from`/`valid_to` columns approximate bitemporal but don't give us "as-of" queries for free. Do we need real bitemporal (XTDB) for the future `oncall_context_for(since=1h)` tool, or is `last_observed_at` filtering enough?
7. **OpenCypher for AI agents.** Does the model write better Cypher than SQL for the same query intent (relevant if we ever expose a `cypher_query` MCP tool)? Worth a small eval before locking in.

---

## 9. Sources

- [Apache AGE GitHub repository](https://github.com/apache/age)
- [Apache AGE FAQ](https://age.apache.org/faq/)
- [Apache AGE multi-graph and namespace docs](https://age.apache.org/age-manual/master/intro/graphs.html)
- [Apache AGE edge-creation performance issue #1925](https://github.com/apache/age/issues/1925)
- [Neo4j licensing FAQ thread](https://github.com/neo4j/neo4j/issues/8331)
- [Neo4j Wikipedia (license summary)](https://en.wikipedia.org/wiki/Neo4j)
- [Memgraph BSL license text](https://github.com/memgraph/memgraph/blob/master/licenses/BSL.txt)
- [Memgraph legal page](https://memgraph.com/legal)
- [Memgraph releases](https://github.com/memgraph/memgraph/releases)
- [KuzuDB abandonment — The Register, Oct 2025](https://www.theregister.com/2025/10/14/kuzudb_abandoned/)
- [Hypermode Dgraph relicensing blog](https://hypermode.com/blog/relicensing-dgraph)
- [Dgraph v25 preview docs](https://docs.hypermode.com/dgraph/v25-preview)
- [JanusGraph releases page](https://github.com/JanusGraph/janusgraph/releases)
- [NebulaGraph repository](https://github.com/vesoft-inc/nebula)
- [FalkorDB GitHub](https://github.com/FalkorDB/FalkorDB)
- [SSPL FAQ — MongoDB](https://www.mongodb.com/legal/licensing/server-side-public-license/faq)
- [ArangoDB licensing change blog](https://arango.ai/blog/evolving-arangodbs-licensing-model-for-a-sustainable-future/)
- [SurrealDB license page](https://surrealdb.com/license)
- [TerminusDB releases](https://github.com/terminusdb/terminusdb/releases)
- [TerminusDB 12 release announcement](https://terminusdb.org/blog/2025-12-08-terminusdb-12-release/)
- [TypeDB Wikipedia (AGPL confirmation)](https://en.wikipedia.org/wiki/TypeDB)
- [Datalevin releases](https://github.com/datalevin/datalevin/releases)
- [Datomic is Free announcement](https://blog.datomic.com/2023/04/datomic-is-free.html)
- [XTDB v2.0 release](https://github.com/xtdb/xtdb/releases/tag/v2.0.0)
- [XTDB site (MPL license confirmed)](https://xtdb.com/)
- [DuckPGQ on DuckDB](https://duckdb.org/docs/current/guides/sql_features/graph_queries)
- [Glean — Indexing code at scale (Meta engineering)](https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/)
- [Glean GitHub repository](https://github.com/facebookincubator/Glean)
- [Oxigraph releases](https://github.com/oxigraph/oxigraph/releases)
- [Cayley GitHub repository](https://github.com/cayleygraph/cayley)
- [Postgres Recursive CTE docs §7.8](https://www.postgresql.org/docs/current/queries-with.html)

---

**Bottom line:** Postgres + Apache AGE. Lowest-risk, most-operable, most-license-clean answer for a regulated-buyer ICP that demands a self-hosted Helm chart. PRD §8 already pointed here — research confirms it's not just a good guess, it's the right call. Dgraph v25 is the credible fallback if scale ever forces the conversation.
