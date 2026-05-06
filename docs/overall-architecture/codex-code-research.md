# Code Search Research and Recommendations for Product 1

**Status:** Draft v0.1
**Author:** Codex
**Date:** 2026-04-27

---

## 1. Scope

This note evaluates current approaches to code search and code-understanding systems relevant to Product 1.

The question is not "what code search exists?" in the abstract. The question is:

**What retrieval architecture should SuperContext Product 1 use if the goal is grounded engineering context across many repos and services?**

---

## 2. Executive summary

The market is converging on four layers:

1. **Exact indexed search** for fast, exhaustive lookup
2. **Structural or symbol-aware retrieval** for code semantics
3. **Agentic exploration** for natural-language answers
4. **Optional semantic retrieval** for fuzzy discovery

The main strategic conclusion is:

**Product 1 should not be built as an embeddings-first codebase chat tool.**

It also should not be built as a pure "Claude Code-style agent over local grep" product.

The strongest architecture for Product 1 is:

- a centralized exact code index
- structural extractors for APIs, events, manifests, and configs
- a provenance-first service graph
- an agentic MCP / PR / CLI layer on top

Embeddings can be useful later, but they should be **secondary retrieval**, not the foundation.

---

## 3. High-level market map

### A. Exact lexical/index-based systems

Examples:

- GitHub Code Search
- Zoekt
- Sourcebot code search
- ripgrep / livegrep style systems

What they do well:

- exact string, regex, and path search
- low latency
- high precision for identifiers, endpoints, config keys, topic names, and protocol strings
- good scale across large codebases
- better support for exhaustive answers

What they do poorly:

- natural-language understanding
- synonymy and fuzzy intent
- multi-step reasoning without an agent layer

### B. Embeddings-first / semantic retrieval systems

Example:

- Cursor codebase indexing

What they do well:

- natural-language lookup
- fuzzy matching when the user does not know exact identifiers
- useful repo chat ergonomics

What they do poorly:

- exactness and exhaustiveness
- dependency-sensitive questions
- trust when the answer must be complete rather than plausible

### C. Agentic search systems

Examples:

- Claude Code / Claude Agent SDK
- Sourcegraph Deep Search
- Sourcebot Ask Sourcebot

What they do well:

- answer synthesis
- iterative exploration
- multi-tool retrieval
- following references, files, commits, and search results

What they do poorly:

- latency and cost
- determinism
- exhaustive coverage unless bounded by strong underlying tools

### D. Structural / syntax-aware systems

Examples:

- tree-sitter queries
- Semgrep patterns
- Comby

What they do well:

- extracting code facts more accurately than regex alone
- finding APIs, callsites, declarations, handlers, config shapes, and event patterns
- powering graph construction and targeted migration workflows

What they do poorly:

- broad natural-language Q&A on their own
- full-system retrieval without surrounding indexing and orchestration

---

## 4. What current systems are actually doing

### GitHub Code Search

GitHub's architecture is a strong reference point for exact search at scale. Their Blackbird engine was built specifically for code search, not general text search, and relies on an index rather than brute-force grep. The public engineering writeup emphasizes ngram-based indexing, symbol extraction, path/content/symbol indexes, and query rewriting for permissions and scopes.

Takeaway:

- serious code search at scale starts with a dedicated index
- exact retrieval remains foundational even when UX looks modern

### Zoekt

Zoekt is a fast trigram-based search engine designed for source code. It supports substring and regex search across many repos and ranks results with code-aware signals. It is one of the clearest open-source examples of the "exact index first" approach.

Takeaway:

- a trigram-style index is a proven substrate for multi-repo code retrieval
- this is a strong prototype or benchmark reference for Product 1

### Sourcebot

Sourcebot combines indexed code search with an MCP server and an agentic `ask_codebase` interface. Its MCP tools expose `grep`, `glob`, file reads, commit listing, symbol definitions/references, and agentic question answering. This is important because it shows a pragmatic modern stack:

- exact search tools
- symbol-aware navigation
- agent on top
- MCP as distribution

Takeaway:

- this is close to the right interaction model for Product 1
- but Sourcebot is still primarily a code-understanding layer, not a service/dependency graph product

### Sourcegraph

Sourcegraph's docs show a hybrid retrieval model. Cody context uses keyword search, Sourcegraph search, and code-graph signals. Deep Search adds an agentic loop over search and code navigation tools. Sourcegraph is effectively validating that natural-language answers work best when backed by exact search plus graph/navigation.

Takeaway:

- the best-in-class commercial pattern is hybrid, not embeddings-only
- agentic search complements exact search; it does not replace it

### Cursor

Cursor's official docs say it indexes the codebase by computing embeddings for each file, updates incrementally, and uses semantic search over code and PR history. This is good for "talk to your repo" and fuzzy retrieval, especially when the user does not know what to search for.

But from the public docs, the primary retrieval primitive is still embedding-based codebase indexing at file level. That is useful for broad assistant UX, but it is a weaker fit for questions where exact dependency and blast-radius correctness matter.

Inference from the docs:

- Cursor is optimized for developer convenience and broad codebase chat
- it is not obviously optimized for exhaustive change-safety reasoning across many services

### Claude Code / Claude Agent SDK

Anthropic's Agent SDK exposes the Claude Code agent loop and built-in tools for reading files, running commands, editing code, and more. Claude Code itself exposes tools such as file reads, globbing, grep-style search, bash, and subagents.

This is powerful for agentic exploration and workflow execution, but it is not, by itself, a centralized enterprise code index. If you build directly on this model alone, you get a strong local agent experience but not the core retrieval infrastructure Product 1 needs.

Takeaway:

- excellent orchestration layer
- weak as the only retrieval substrate
- strong prototype path, weak moat if used alone

### tree-sitter / Semgrep / Comby

These are not "code search products" in the same sense, but they matter a lot for Product 1.

- tree-sitter queries support syntax-tree pattern matching
- Semgrep supports code-like structural patterns, not just text patterns
- Comby provides lightweight structural search and rewrite

These systems are especially relevant for extracting facts that a plain text index misses or makes brittle:

- route definitions
- gRPC handlers
- Kafka topic usage
- config wiring
- auth middleware
- SDK callsites
- schema usage patterns

Takeaway:

- Product 1 needs structural extraction, not just text retrieval

---

## 5. Comparison by approach

| Approach | Best at | Weak at | Fit for Product 1 |
|---|---|---|---|
| Exact lexical index | exhaustive lookup, speed, regex, identifiers, configs | fuzzy NL discovery | **Essential** |
| Embeddings / semantic RAG | fuzzy questions, repo chat, vague prompts | exactness, completeness, dependency reasoning | **Secondary** |
| Agentic search | synthesis, exploration, multi-step reasoning | latency, cost, determinism | **Essential as interface layer** |
| Structural search / parsing | extracting code facts and edges | broad QA on its own | **Essential for graph building** |

---

## 6. What this means for SuperContext

The important pushback is this:

**Product 1 is not "just code search."**

It uses code search, but the product is actually:

- code retrieval
- structural fact extraction
- dependency graph construction
- grounded answering in workflows

If Product 1 is built as generic code chat, it will look too much like Cursor, Sourcebot, or a Claude wrapper.

If Product 1 is built as pure indexed search, it will look like a better GitHub/Sourcegraph search box, but not like a workflow-critical product.

The wedge is the combination:

- exact code retrieval
- service and contract extraction
- blast-radius reasoning
- PR-time and IDE-time surfaces

That combination is materially narrower and stronger.

---

## 7. Recommendations

### Recommendation 1: Build a hybrid retrieval stack, not a single-method product

Product 1 should combine:

1. exact indexed search
2. structural extraction
3. service graph
4. agentic answer layer

This is the architecture most aligned with the actual user promise.

### Recommendation 2: Do not make embeddings the primary retrieval layer

Embeddings are helpful for:

- fuzzy onboarding questions
- approximate matching
- historical PR lookup
- eventually docs and tickets in Product 2

Embeddings are not the right foundation for:

- "who consumes this field?"
- "which services call this endpoint?"
- "what breaks if I delete this event?"

Those need exactness, provenance, and often exhaustiveness.

### Recommendation 3: Do not ship a pure agent-over-local-files architecture as the core product

Using Claude Agent SDK or a similar agent loop is a good way to prototype the UX.

It is not enough as the product backend because:

- retrieval will be bounded by the checked-out workspace or ad hoc file access
- latency will be higher
- reproducibility will be weaker
- permissioning and central indexing will be harder
- there is little moat if the product is just "a good prompt over grep and read"

### Recommendation 4: Make structural extraction a first-class part of MVP

For Product 1, structural extraction should be part of the core engine from the start, at least for:

- OpenAPI / gRPC / GraphQL / AsyncAPI
- typed client callsites
- route declarations
- Kafka topic producers and consumers
- Helm / Kubernetes manifests
- config-derived service URLs

Regex alone will become brittle here.

### Recommendation 5: Treat the graph as the proprietary layer

The long-term value is not in:

- a regex engine
- an embeddings index
- a generic agent harness

The value is in:

- extracted facts
- cross-repo dependency edges
- provenance
- freshness
- workflow-specific reasoning

This is where Product 1 differentiates from generic code search tools.

---

## 8. Recommended Product 1 architecture

### Layer 1: Exact search index

Capabilities:

- substring search
- regex search
- path and repo filters
- branch / commit awareness
- symbol index where available

Implementation options:

- build on Zoekt-like ideas
- benchmark against Sourcebot-like behavior
- use ripgrep locally for fallback and development workflows only

### Layer 2: Structural extraction

Capabilities:

- parse contracts and handlers
- identify clients and callsites
- extract event edges
- detect deploy/config edges

Implementation options:

- tree-sitter for AST-oriented extraction
- Semgrep-style patterns for practical multi-language matching
- targeted parsers for OpenAPI / proto / GraphQL / AsyncAPI / YAML

### Layer 3: Service graph

Capabilities:

- store entities, edges, provenance, freshness
- unify static and runtime signals
- answer blast-radius and deploy-blocker queries

This is the Product 1 core.

### Layer 4: Agentic interface

Capabilities:

- MCP tools
- PR bot reasoning
- CLI queries
- natural-language synthesis over the graph and search layers

Implementation option:

- Claude Agent SDK is a reasonable orchestration layer for prototypes and potentially for some production-facing agent flows

But the agent should call your tools. It should not be your retrieval engine.

### Layer 5: Optional semantic retrieval

Use later for:

- fuzzy onboarding questions
- synonym expansion
- similar-file discovery
- PR-history lookup
- eventually docs/tickets/files in Product 2

This should be additive, not foundational.

---

## 9. Practical build recommendation

If the goal is to move fast without painting yourself into a corner, the best path is:

1. **Start with an exact multi-repo index plus file/symbol read APIs**
2. **Add structural extractors for contracts, clients, events, and manifests**
3. **Build the service graph and provenance model**
4. **Expose narrow MCP tools and PR workflows**
5. **Only then add semantic retrieval where it clearly improves UX**

That sequencing gives you:

- a credible MVP
- stronger correctness
- a better moat
- a clean path into Product 2 later

---

## 10. Specific recommendations on the tools you mentioned

### Sourcebot

Good reference and possible benchmark.

Recommendation:

- study it closely
- possibly use it as a speed benchmark or prototype reference
- do not mistake it for the core differentiated product

### Claude Agent SDK

Good orchestration layer.

Recommendation:

- use it for prototyping agentic workflows and MCP interactions
- do not rely on it as the main retrieval architecture

### Cursor-style semantic indexing

Useful pattern for future UX improvements.

Recommendation:

- do not make this the Product 1 core
- consider it later as an auxiliary retrieval layer

---

## 11. Final recommendation

If forced to choose a primary architectural posture for Product 1, choose:

**Sourcegraph / Sourcebot / GitHub-style exact search and navigation as the substrate, plus your own structural extraction and service graph, with an agentic layer on top.**

Do **not** choose:

- Cursor-style embeddings-first retrieval as the core
- pure Claude-agent-over-local-files as the core

The simplest crisp statement is:

**Build a graph product powered by code search, not a code search product that later hopes to become a graph.**

---

## 12. Sources

Primary sources used for this note:

- GitHub Blog, "The technology behind GitHub's new code search"  
  https://github.blog/engineering/the-technology-behind-githubs-new-code-search/
- GitHub Code Search  
  https://github.com/features/code-search/
- Sourcegraph docs, Deep Search  
  https://sourcegraph.com/docs/deep-search
- Sourcegraph docs, Cody Context  
  https://sourcegraph.com/docs/cody/core-concepts/context
- Sourcegraph Zoekt repository  
  https://github.com/sourcegraph/zoekt
- Sourcebot docs overview  
  https://docs.sourcebot.dev/
- Sourcebot MCP server docs  
  https://docs.sourcebot.dev/docs/features/mcp-server
- Sourcebot Ask overview  
  https://docs.sourcebot.dev/docs/features/ask/overview
- Cursor docs, Codebase Indexing  
  https://docs.cursor.com/context/codebase-indexing
- Claude Agent SDK overview  
  https://code.claude.com/docs/en/agent-sdk/overview
- Claude Code settings and built-in tools  
  https://code.claude.com/docs/en/settings
- tree-sitter queries  
  https://tree-sitter.github.io/tree-sitter/using-parsers/queries/
- Semgrep pattern syntax  
  https://semgrep.dev/docs/writing-rules/pattern-syntax
- Comby  
  https://comby.dev/
