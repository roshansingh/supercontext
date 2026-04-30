# ADR-0005: Use Modular Evidence Retrieval with Coordinate Fetch and a Selective Retrieval Ladder

- **Status:** Accepted
- **Date:** 2026-04-29
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

`PRD.md` requires every code fact returned by SuperContext to carry `commit_sha + file:line`, and says that if the product cannot cite a fact, it should not say it. It also requires refusal when the graph is uninstrumented rather than guessing.

The previous accepted decisions define the surrounding system:

- `ADR-0001`: Claude Agent SDK for internal agent runtime
- `ADR-0002`: MCP as the public customer-facing protocol
- `ADR-0003`: PostgreSQL + Apache AGE as the initial graph storage layer
- `ADR-0004`: canonical typed graph plus candidate / enrichment sidecar

Evidence retrieval is the layer that grounds graph claims in raw source material. It must work for enterprise customers with many repositories, multiple programming languages, and self-hosted / no-egress deployment requirements.

The evidence-retrieval research and debate converged on four points:

- Evidence retrieval is a first-class runtime substrate, not just a fallback after graph retrieval.
- Commit-pinned coordinate fetch is mandatory for surfaced or safety-critical claims.
- Search should use a budgeted ladder: lexical, then structural, then agentic exploration.
- SuperContext should reuse OSS primitives but own the orchestration, provenance contract, refusal semantics, and adapter interfaces.

## Decision

**Build a modular evidence-retrieval layer owned by SuperContext.**

The runtime model has two modes:

1. **Mode A: commit-pinned coordinate fetch**
2. **Mode B: selective retrieval ladder**

Graph retrieval and evidence retrieval are both first-class. The graph provides structure; evidence retrieval proves and grounds claims.

## Mode A: coordinate fetch

Mode A fetches raw bytes from source control using a pinned coordinate:

`repo + commit_sha + path + line_start + line_end`

Mode A must run for:

- every graph fact surfaced in a final answer
- every cited code fact
- every safety-critical claim that affects refusal, blocking, blast radius, or deploy sequencing

Mode A should use a content-addressed cache keyed by immutable coordinates. It must never silently fall back to `HEAD` when a coordinate cannot be resolved.

Initial OSS choices:

- `go-git` for Go runtimes
- `pygit2` for Python runtimes
- shell `git` may be retained as a diagnostic or fallback path, not the primary API

## Mode B: selective retrieval ladder

Mode B is a search ladder that runs selectively, not automatically for every query.

It runs when:

- the user asks a source/evidence question
- the query is literal or cross-repo
- the query is conceptual enough that exact graph coordinates are unlikely to be sufficient
- the graph returns `uninstrumented`, stale, or low-confidence coverage
- the operation is safety-critical and needs independent grounding

The ladder:

1. **Lexical search**
   - Default v1 backend: `ripgrep`
   - Scalable backend extension: `Zoekt`
   - Used for names, exact strings, symbols, errors, endpoints, topics, configs, and manifests

2. **Structural search**
   - Default v1 backend: `ast-grep` over `tree-sitter`
   - Used for definitions, call sites, imports, route declarations, framework patterns, and typed code shapes

3. **Agentic exploration**
   - Default v1 backend: Claude Agent SDK Explorer subagent with a narrow tool allowlist such as `Glob`, `Grep`, and `Read`
   - Used only when lexical and structural search do not sufficiently ground the answer, or when ambiguity / uninstrumented coverage requires reasoning
   - Must be budgeted by configurable limits; this ADR does not set numeric defaults

## OSS and build decisions

### Use now

- `go-git` / `pygit2` for commit-pinned coordinate fetch
- `ripgrep` for default lexical search
- `tree-sitter` as the parsing substrate
- `ast-grep` for structural search
- Claude Agent SDK Explorer subagent for budgeted agentic exploration

### Build ourselves

- Evidence retrieval orchestration
- Adapter interfaces
- Coordinate-fetch API
- Provenance and citation contract
- Refusal semantics
- Merge logic between graph retrieval and evidence retrieval
- Query-class routing and budget gates
- Contract tests for the evidence layer

### Support later / optional

- `Zoekt` as the scalable indexed lexical-search backend when measured repo scale or p95 latency requires it
- `Semble` as an optional / experimental fuzzy code-search adapter or benchmark, not as the primary evidence backbone

### Reference only

- `Sourcebot`

Sourcebot is a useful reference architecture for code search, MCP exposure, and indexed-search ergonomics. It should not be the runtime dependency for Product 1 because it brings a larger product surface and does not own SuperContext's graph model, provenance contract, or refusal semantics.

### Skip as primary path

- Code-chunk embeddings
- Embeddings-first evidence retrieval
- Sourcebot as the runtime backbone
- Semble as the core evidence layer

## Adapter boundaries

The evidence layer must be written as an open-source enterprise platform, not as a fixed implementation.

Required interfaces:

- `CoordinateFetcher`
- `LexicalSearchBackend`
- `StructuralSearchBackend`
- `AgenticExplorer`
- `EvidenceContract`

The default v1 stack is:

- `CoordinateFetcher`: `go-git` or `pygit2`
- `LexicalSearchBackend`: `ripgrep`
- `StructuralSearchBackend`: `ast-grep` / `tree-sitter`
- `AgenticExplorer`: Claude Agent SDK

The platform must allow later adapters, including `Zoekt`, without changing MCP tool contracts or graph query semantics.

## Polyglot enterprise support

Polyglot support is layered:

- Coordinate fetch works for any Git-tracked text file.
- Lexical search works across all text languages.
- Structural search support improves incrementally by language and framework.
- Agentic exploration covers gaps, but its output must be treated as lower-confidence evidence unless promoted by validation.

This means Product 1 can serve polyglot enterprises early, while deeper structural precision grows by language and framework over time.

## Runtime orchestration

Runtime behavior:

- Graph retrieval provides typed operational structure.
- Evidence retrieval provides exact raw grounding.
- Mode A runs for surfaced and safety-critical graph facts.
- Mode B runs selectively based on query class, coverage, ambiguity, and budget.
- Answer synthesis merges graph structure and evidence results.
- Missing bytes, missing grounding, or exhausted budget must return explicit refusal metadata rather than a silent best guess.

## Consequences

### Positive

- Preserves provenance-first trust.
- Keeps the system self-hosted and no-egress friendly.
- Avoids adopting a full external code-search product as a core dependency.
- Gives a clear path from simple v1 search to indexed enterprise-scale search.
- Keeps the product surface centered on SuperContext's graph and evidence contracts.

### Negative

- Requires us to build orchestration and adapter interfaces.
- Requires benchmarks before choosing hard budget defaults.
- `ripgrep` may not be enough for large enterprise repo fleets; `Zoekt` should be planned as a measured scale extension.
- Structural precision will vary by language and framework until rule coverage matures.

### Neutral

- This decision does not prohibit semantic or fuzzy retrieval later.
- This decision does not require `Zoekt` on day one.
- This decision does not make Claude Agent SDK part of the public evidence API.

## Open follow-up work

1. Benchmark `ripgrep` p95 across representative multi-repo enterprise fixtures.
2. Define the first `Zoekt` adapter boundary before scale requires it.
3. Decide the initial language/framework coverage for `ast-grep` rules.
4. Define default agentic exploration budgets from measured latency and token data.
5. Evaluate Semble as a fuzzy-search benchmark or optional adapter, not as a core dependency.

## References

- `PRD.md` §6.1, §6.2, §7
- `PLATFORM-PRD.md` §8, §9, §10
- `ADR-0001`
- `ADR-0002`
- `ADR-0003`
- `ADR-0004`
- `evidence-retrieval/claude-evidence-retrieval-research.md`
- `evidence-retrieval/codex-evidence-retrieval-research.md`
- `evidence-retrieval/codex-runtime-retrieval-patterns.md`
- `debates/1-2026-04-29-finalize-evidence-retrieval-architecture.md`

