# Graph Building Research for SuperContext Product 1

> **✅ RESOLVED — 2026-04-29.** The final decision is captured in [`GRAPH-BUILDING-RECOMMENDATION.md`](./GRAPH-BUILDING-RECOMMENDATION.md) and [`../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md`](../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md). This note is preserved as research history and as a supporting input to the accepted architecture. Its core posture is adopted, while the exact canonical entity and relation vocabulary remains open for targeted follow-up research.

**Status:** Draft v0.1
**Date:** 2026-04-28
**Scope:** Decide how the Product 1 graph should be built, and whether it should be a strict typed operational graph or a looser GraphRAG-style graph.

---

## 1. Decision

For **Product 1**, build a **strict canonical operational graph** with:

- a clear typed schema for core entities and relations
- deterministic ingestion wherever possible
- provenance and freshness on every fact
- a separate **candidate / enrichment layer** for uncertain or LLM-inferred facts

Do **not** make the Product 1 graph a noisy GraphRAG-style graph built directly from LLM extraction over mixed source material.

Also do **not** over-rotate into a heavyweight semantic-web ontology project.

The right answer is:

**a narrow, versioned, strongly typed operational ontology for canonical facts, plus a looser sidecar layer for enrichment and exploration.**

---

## 2. Why this decision matters

This is probably the most important product architecture decision because it controls whether SuperContext answers:

- deterministically
- audibly
- with refusal when coverage is missing
- with enough precision for change-safety workflows

The current MCP tools are not generic corpus Q&A. They are mostly:

- `find_callers`
- `find_callees`
- `get_event_consumers`
- `get_event_producers`
- `blast_radius`
- `deploy_blockers_for`

These require:

- exact entity identity
- exact relation semantics
- multi-hop traversal over typed edges
- evidence-backed confidence
- the ability to say “we do not know”

A noisy graph is much less dangerous for “summarize themes in these docs” than it is for “can I safely remove this field?”

That is why Product 1 should not use GraphRAG-style graph construction as the canonical graph.

---

## 3. What GraphRAG is good at

Microsoft’s GraphRAG work is aimed at **global sensemaking over text corpora**. Their paper explicitly frames the problem as answering broad corpus-level questions such as “What are the main themes in the dataset?” by deriving an entity graph from source documents and summarizing communities.

Sources:

- https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/
- https://www.microsoft.com/en-us/research/project/graphrag/

Neo4j’s LLM Knowledge Graph Builder has the same flavor: it turns unstructured text into a knowledge graph for exploratory graph-powered RAG.

Source:

- https://neo4j.com/blog/developer/graphrag-llm-knowledge-graph-builder/

That style of graph construction is useful when:

- the sources are mostly prose
- the user wants discovery and summarization
- incomplete or fuzzy edges are acceptable
- the graph is primarily a retrieval/sensemaking aid

That is **not** the core Product 1 workload.

---

## 4. Why GraphRAG-style graph building is wrong for the Product 1 core

### 4.1 The core sources are not mainly prose

Product 1 is built from:

- code
- API specs
- schemas
- manifests
- runtime traces
- service catalog metadata

These are closer to **operational system facts** than to free-form narrative documents.

### 4.2 The core questions require precise semantics

`CALLS`, `CONSUMES`, `PRODUCES`, `DEPLOY_BLOCKED_BY`, and `OWNED_BY` are not fuzzy relations.

If the system says:

- service A calls service B
- service C consumes topic X
- deployment Y must precede deployment Z

those claims need to be grounded in structured evidence.

### 4.3 Product 1 needs refusal-on-coverage-gaps

The PRD explicitly requires refusal when the graph is uninstrumented.

A GraphRAG-style graph built from LLM extraction is weaker here because:

- missing facts can be mistaken for absent facts
- entity resolution is noisier
- edge semantics are softer
- provenance is harder to keep mechanically tight

### 4.4 The graph is a system of record for workflows, not just retrieval

This graph will drive:

- PR comments
- IDE-time warnings
- deploy sequencing
- migration planning
- impact memos

That means the canonical graph must behave more like an **operational fact system** than like an exploratory semantic layer.

---

## 5. What the research suggests instead

There are three useful patterns from adjacent systems:

### 5.1 Glean pattern: typed facts and schema discipline

Glean stores data as **facts** under explicit **predicates** in a schema. Facts are unique, typed, and evolvable under compatibility rules.

Sources:

- https://glean.software/docs/schema/basic/
- https://glean.software/docs/schema/changing/
- https://glean.software/docs/introduction/

This matters because Product 1 needs fact-like guarantees more than document-like flexibility.

### 5.2 Backstage pattern: authoritative ingestion plus processing

Backstage ingests from authoritative sources, processes entities, emits relations, and stitches final entities after validation and processing.

Sources:

- https://backstage.io/docs/features/software-catalog/life-of-an-entity/
- https://backstage.io/docs/features/software-catalog/well-known-relations/
- https://backstage.io/docs/features/software-catalog/descriptor-format

This is a strong design pattern for Product 1:

- authoritative source ingestion
- processors
- relation extraction
- final stitched canonical entities

### 5.3 OpenLineage pattern: strict core with extensible facets

OpenLineage uses a small set of core entities but allows extension via **facets**, which are namespaced metadata attachments.

Sources:

- https://openlineage.io/docs/1.30.0/guides/facets/
- https://openlineage.io/docs/next/spec/facets/

This is useful because Product 1 should have:

- a strict core model
- extension points for metadata and later product needs

without turning the whole graph into an ungoverned blob.

---

## 6. Recommended graph-building model

### 6.1 Canonical graph

This is the graph the MCP tools query by default.

Characteristics:

- strongly typed nodes and relationships
- stable identifiers
- deterministic relation semantics
- versioned schema
- explicit provenance
- freshness metadata
- confidence classes

This graph should only contain facts that meet promotion rules.

### 6.2 Candidate graph

This is where uncertain, inferred, or partially resolved information lives.

Characteristics:

- lower-confidence facts allowed
- LLM-assisted extraction allowed
- dynamic callsite hypotheses allowed
- ambiguous alias mappings allowed
- agentic exploration output allowed

Candidate facts should **not** be silently merged into canonical facts.

They should be:

- separately labeled
- separately queryable
- optionally shown as low-confidence evidence
- promotable only after validation

### 6.3 Evidence layer

Every canonical or candidate fact should be backed by explicit evidence references.

Examples:

- source file + line range
- trace observation
- schema registry record
- catalog entity reference
- manifest path
- agentic exploration transcript pointer

This evidence layer is essential for:

- citations
- debugging
- trust
- reindexing
- promotion workflows

---

## 7. The ontology question

The right answer is:

**Yes, Product 1 needs a clear ontology. No, it should not be an academic heavyweight ontology project.**

That distinction matters.

### What Product 1 should have

- a small number of versioned core entity types
- a controlled set of relation types with defined semantics
- required properties on important edges
- strict ID rules
- additive evolution rules
- namespaced extension metadata

### What Product 1 should avoid

- RDF-first or OWL-first modeling
- trying to model every imaginable enterprise concept up front
- dozens of overlapping edge types without governance
- LLM-generated node and relation types entering the canonical model ad hoc

This product needs an **operational ontology**, not a research ontology.

---

## 8. Recommended canonical entity model

### Core entities

- `Service`
- `Endpoint`
- `Operation`
- `EventTopic`
- `SchemaVersion`
- `Repo`
- `Team`
- `Person`
- `Deployable`
- `Deployment`
- `Environment`
- `Cluster`
- `Namespace`

### Core relation families

- ownership
- call graph
- event graph
- schema lineage
- deploy topology
- deployment sequencing

### Example canonical relation types

- `OWNS_ENDPOINT`
- `IMPLEMENTS`
- `USES_SCHEMA`
- `CALLS`
- `CALLS_SERVICE`
- `PRODUCES`
- `CONSUMES`
- `CURRENT_SCHEMA`
- `EVOLVES_TO`
- `OWNED_BY`
- `DEFINED_IN`
- `FOR_SERVICE`
- `DEPLOYS_TO`
- `DEPLOY_BLOCKED_BY`

Every one of these should have a one-paragraph semantic definition internally.

If a relation cannot be defined crisply, it probably should not be canonical yet.

---

## 9. Recommended graph-building pipeline

## Step 1: Ingest authoritative sources

Sources include:

- Git repos
- OpenAPI / proto / GraphQL / AsyncAPI
- manifests
- traces
- service catalogs
- schema registries

This stage should bring in source-native records without trying to “reason” too early.

## Step 2: Normalize identities

Before relation stitching, assign canonical IDs.

Examples:

- `service://checkout`
- `repo://github.com/acme/checkout-service`
- `endpoint://checkout/POST_/v1/orders`
- `event://kafka/order.created`
- `schema://proto/acme.orders.v3#sha256:...`

If IDs are weak, the whole graph will rot.

This is the first place where Product 1 should be uncompromising.

## Step 3: Extract deterministic facts

Use deterministic or near-deterministic extractors first:

- specs to endpoints and operations
- typed client callsites to endpoint relations
- topic declarations to producer/consumer relations
- manifests to deploy topology
- catalog metadata to ownership
- traces to observed runtime edges

LLMs should not be the first-line extractor for these.

## Step 4: Stitch and canonicalize

Merge extracted facts into canonical entities and canonical edge records.

This stage should:

- deduplicate aliases
- collapse source-specific representations
- choose canonical node identity
- attach provenance summaries
- assign confidence classes

Backstage’s provider → processor → stitched entity pattern is a good mental model here.

## Step 5: Derive secondary edges

Examples:

- `CALLS_SERVICE` derived from endpoint-level `CALLS`
- deploy dependency edges derived from lower-level rollout facts
- neighborhood summaries

Derived edges should be marked as derived, not confused with direct evidence edges.

## Step 6: Validate graph invariants

Examples:

- every `Endpoint` must belong to one `Service`
- every `CALLS` edge must specify protocol and evidence
- every canonical `Service` should have at least one source of ownership
- every `SchemaVersion` lineage edge should be acyclic where expected

This is where the graph behaves like a product, not like a best-effort extraction output.

## Step 7: Optional agentic / LLM enrichment

Only after deterministic extraction and stitching:

- resolve dynamic aliases
- infer probable topic mappings
- detect convention-based relations
- generate summaries
- propose candidate facts

These outputs should default to **candidate layer**, not canonical layer.

## Step 8: Promote candidate facts selectively

Promotion should require at least one of:

- corroboration from deterministic evidence
- repeated observation across runs
- explicit rule-based validation
- human review for high-risk relation classes

This is the critical control point that prevents graph drift.

---

## 10. Confidence model

The graph should not have a single undifferentiated notion of truth.

Recommended confidence classes:

- `authoritative`
- `derived`
- `observed`
- `inferred`
- `candidate`

Examples:

- service ownership from Backstage: `authoritative`
- service-to-service edge derived from endpoint calls: `derived`
- runtime edge from trace data: `observed`
- alias mapping inferred by an agent: `inferred`
- unresolved possible consumer from LLM exploration: `candidate`

This is much better than pretending all edges are equally certain.

---

## 11. Schema governance recommendation

Product 1 should have **schema governance**, but keep it lightweight.

Recommended rules:

- version the core schema
- prefer additive changes
- every new canonical node or edge type needs a semantic definition
- every new canonical edge type needs at least one deterministic or authoritative extractor path
- namespaced custom metadata should be allowed via extension properties or facet-like attachments

This is close in spirit to:

- Glean’s compatibility-aware schema evolution
- OpenLineage’s extensible facets

without copying either system literally.

---

## 12. What should stay noisy

The following are acceptable in the noisy / candidate / enrichment layer:

- summaries of service behavior
- likely alias mappings
- probable dependency hints
- issue or incident linkages inferred from text
- doc-to-service associations from README/ADR text

These are useful.

They just should not be the substrate for:

- `blast_radius`
- `find_callers`
- `get_event_consumers`
- `deploy_blockers_for`

Those should run on canonical facts first.

---

## 13. Answer to the core question

### Does Product 1 need a high-quality, strictly structured graph?

**Yes, for the canonical operational layer.**

### Does it need a heavyweight ontology?

**No.** It needs a narrow operational ontology, not a semantic-web research project.

### Can it use a noisier GraphRAG-like graph?

**Yes, but only as a secondary enrichment and exploration layer.**

### Should the GraphRAG-like graph be the product core?

**No.**

That would make the highest-value Product 1 workflows less trustworthy precisely where the product needs to be strongest.

---

## 14. Final recommendation

Build Product 1 as a **two-tier graph system**:

### Tier 1: Canonical operational graph

- strict
- typed
- governed
- provenance-first
- directly powers MCP workflows

### Tier 2: Candidate / enrichment graph

- noisier
- more flexible
- can use LLM extraction and GraphRAG-style techniques
- supports summaries, exploration, and future Product 2 expansion

This gives you the best of both:

- Product 1 stays trustworthy enough for engineering change-safety
- the platform still has room to grow into richer graph-powered retrieval later

The simplest summary is:

**Do not build Product 1 as GraphRAG. Build a strict operational graph, and let GraphRAG-style enrichment sit beside it.**

---

## 15. Sources

- GraphRAG paper / Microsoft Research  
  https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/
- Microsoft Project GraphRAG  
  https://www.microsoft.com/en-us/research/project/graphrag/
- Neo4j LLM Knowledge Graph Builder  
  https://neo4j.com/blog/developer/graphrag-llm-knowledge-graph-builder/
- Glean basic concepts  
  https://glean.software/docs/schema/basic/
- Glean schema evolution  
  https://glean.software/docs/schema/changing/
- Glean introduction  
  https://glean.software/docs/introduction/
- Backstage life of an entity  
  https://backstage.io/docs/features/software-catalog/life-of-an-entity/
- Backstage well-known relations  
  https://backstage.io/docs/features/software-catalog/well-known-relations/
- Backstage descriptor format  
  https://backstage.io/docs/features/software-catalog/descriptor-format
- OpenLineage facets  
  https://openlineage.io/docs/1.30.0/guides/facets/
- OpenLineage next facets spec  
  https://openlineage.io/docs/next/spec/facets/
