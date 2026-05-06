# Runtime Retrieval Patterns

> **RESOLVED — 2026-04-29.** The final runtime decision is captured in [`EVIDENCE-RETRIEVAL-RECOMMENDATION.md`](./EVIDENCE-RETRIEVAL-RECOMMENDATION.md) and [`../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`](../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md). This document is preserved as research history. The accepted rule is graph and evidence as first-class substrates, with Mode A always for surfaced/safety-critical facts and Mode B selectively invoked by query class, coverage, ambiguity, and budget.

**Status:** Draft v0.1
**Date:** 2026-04-28
**Scope:** Define how runtime evidence retrieval should interact with graph retrieval in SuperContext Product 1.

---

## 1. Framing

At runtime, Product 1 has two distinct retrieval substrates:

- **Graph retrieval**
  - query the canonical service/dependency graph
  - get entities, relations, paths, neighborhoods, and derived operational facts

- **Evidence retrieval**
  - query the exact index / raw source evidence layer
  - get file matches, symbol matches, config hits, manifest matches, and source-level provenance

The question is not whether both exist.

The question is:

**When a user asks a question, how should runtime evidence retrieval interact with graph retrieval?**

---

## 2. The three runtime patterns

## Option 1: Graph-first, evidence-second

### How it works

1. Run the graph query first
2. Get candidate entities / edges / paths
3. Retrieve source evidence for the graph result
4. Use the evidence for:
   - citations
   - snippets
   - verification
   - UI detail
   - gap-fill if a graph edge looks weak

### Best for

- `find_callers`
- `find_callees`
- `get_event_consumers`
- `get_event_producers`
- `blast_radius`
- `deploy_blockers_for`

### Why it is attractive

- keeps Product 1 centered on the canonical graph
- efficient for operational dependency questions
- natural for PR bot and IDE safety workflows
- makes the graph the main source of system understanding

### Downsides

- weak for literal/source-driven questions
- can miss useful evidence if the graph query is too narrow
- tends to assume the graph is the main entry point even when the user is really asking for raw code evidence

---

## Option 2: Evidence-first, graph-second

### How it works

1. Run exact evidence retrieval directly from the user query
2. Get source-level matches first
3. Map those matches into graph entities where useful
4. Use graph retrieval only as follow-up structure

### Best for

- “where is this exact config key used?”
- “show me all uses of this header”
- “find this topic string across repos”
- “where does this environment variable appear?”

### Why it is attractive

- best for exact literal questions
- exploits the strength of the index directly
- avoids forcing every question through graph semantics

### Downsides

- weak default for dependency and blast-radius workflows
- can produce lots of raw matches without enough system structure
- can over-bias the product toward code search instead of graph-backed reasoning

---

## Option 3: Parallel retrieval

### How it works

1. Run graph retrieval and evidence retrieval from the same user query
2. Let both return candidate results independently
3. Merge them in the answer layer
4. Use the graph for structure and the evidence layer for grounding

### Best for

- mixed operational questions
- ambiguous questions
- safety-critical questions where both structure and raw evidence matter
- future natural-language MCP interactions

### Why it is attractive

- does not force an early commitment to one substrate
- strongest overall answer quality when questions mix system reasoning and source evidence
- fits the Product 1 reality that:
  - graph gives system understanding
  - exact search gives raw grounding
- likely best fit for natural language workflows where user intent is not perfectly classified upfront

### Downsides

- more expensive at runtime
- requires stronger orchestration and result-merging logic
- can return redundant or conflicting information unless the synthesis layer is disciplined

---

## 3. What the current research suggests

The two existing overall-architecture notes point to slightly different emphases:

### Claude architecture note

This note is more **graph-first**.

It treats:

- the graph as the main runtime substrate
- agentic or exact evidence retrieval as support, gap-fill, or ingestion assistance

This is most visible in the architecture section and in the recommendation that the graph is the spine while agentic search is a helper, not the primary retrieval substrate.

Reference:

- [`docs/overall-architecture/claude-code-research.md`](/Users/maruti/work/bettercontext/docs/overall-architecture/claude-code-research.md)

### Codex architecture note

This note is more explicitly **dual-retrieval**.

It treats:

- the exact index as a real runtime layer
- the graph as another real runtime layer
- the answer layer as the place where both are combined

Reference:

- [`docs/overall-architecture/codex-code-research.md`](/Users/maruti/work/bettercontext/docs/overall-architecture/codex-code-research.md)

### Synthesis

Taken together, the current research suggests:

- Product 1 should not be evidence-only
- Product 1 should not be graph-only
- the graph should lead many core workflows
- evidence retrieval should remain a first-class runtime capability

That points most naturally to **parallel retrieval**, with graph-led behavior for some workflows and evidence-led behavior for others.

---

## 4. Current leaning

Current leaning:

**Option 3: Parallel retrieval**

Why:

- it best matches the actual product shape
- it preserves the graph as the operational core
- it preserves exact evidence as a first-class runtime substrate
- it avoids prematurely forcing all runtime behavior into graph-first or evidence-first routing

This does **not** mean every query must always do full work on both sides forever.

A practical implementation can still optimize by query class:

- graph-heavy questions can bias toward graph retrieval
- literal/source-heavy questions can bias toward evidence retrieval
- ambiguous or safety-critical questions can run both fully

But at the architecture level, the clean framing is:

**parallel retrieval is the default model**

---

## 5. Recommended terminology

To keep the architecture discussions clear, use:

- **Graph retrieval layer**
- **Evidence retrieval layer**
- **Answer synthesis layer**

This is cleaner than treating evidence retrieval as just a post-processing step after graph queries.

---

## 6. Final conclusion

The runtime architecture should be described as:

- the graph returns structured operational understanding
- the evidence layer returns exact raw grounding
- the answer layer decides how to combine them

The three valid patterns are:

1. graph-first, evidence-second
2. evidence-first, graph-second
3. parallel retrieval

Current leaning:

**parallel retrieval**

because it best preserves both strengths:

- graph for system reasoning
- evidence retrieval for grounding and exactness
