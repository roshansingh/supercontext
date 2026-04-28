# Evidence Retrieval Research

**Status:** Draft v0.1
**Date:** 2026-04-28
**Scope:** Research how the evidence retrieval layer should work for SuperContext Product 1, with emphasis on exact indexed code search systems and Claude Code’s agentic search behavior.

---

## 1. Decision

The evidence retrieval layer for Product 1 should be built as:

- an **exact indexed search substrate** for code and config evidence
- plus an **agentic query planner** that can drive that substrate intelligently

In practical terms:

- use a **Sourcebot / Zoekt-style exact index** as the retrieval backbone
- use a **Claude Code-style agentic search pattern** as the orchestration behavior
- do **not** build the evidence layer as embeddings-first semantic code search

The shortest summary is:

**Exact index for recall and precision. Agentic planning for intelligence.**

---

## 2. What the evidence retrieval layer needs to do

The evidence retrieval layer is not trying to answer the whole product question by itself. Its job is to return raw, exact, source-grounded evidence such as:

- file matches
- symbol hits
- config and manifest matches
- branch/ref-aware source reads
- commit-scoped evidence
- source snippets for citations

At runtime, this layer should support:

- graph verification
- citation generation
- literal/source-driven user questions
- graph gap-fill
- ambiguity resolution

That means the retrieval substrate must optimize for:

- exactness
- scale
- repo/ref/file filters
- fast file reads after search
- predictable ranking

---

## 3. Main patterns in the market

## Pattern A: Exact indexed search

Examples:

- Zoekt
- Sourcebot code search
- Sourcegraph indexed search

This pattern gives:

- exact substring matching
- regex matching
- repo / file / language filters
- fast multi-repo search
- ranking based on code-aware signals

This is the strongest foundation for Product 1 evidence retrieval.

## Pattern B: Agentic grep/read loops

Example:

- Claude Code

This pattern gives:

- flexible exploration
- query reformulation
- iterative narrowing
- choosing what file to read next
- strong behavior on vague tasks

But by itself it is not a centralized evidence retrieval system.

## Pattern C: Embeddings-first semantic code retrieval

Example:

- Cursor-style codebase indexing

This pattern gives:

- fuzzy natural-language lookup
- approximate semantic discovery

But it is weaker for:

- exact identifiers
- exhaustive evidence gathering
- source-grounded operational questions

For Product 1, this should be optional later, not the backbone.

---

## 4. What Sourcebot and Zoekt tell us

### Zoekt

Zoekt is a fast trigram-based code search engine built for source code. It supports:

- fast substring and regex matching
- a query language with boolean operators
- cross-repo search
- ranking using code-aware signals such as symbol matches
- web, JSON API, and gRPC surfaces

Source:

- https://github.com/sourcegraph/zoekt

What this means:

- Zoekt is a strong low-level retrieval substrate
- it is excellent for exact evidence retrieval
- by itself it is a search engine, not the full evidence retrieval product

### Sourcegraph

Sourcegraph’s docs confirm the same architecture pattern:

- indexed search uses Zoekt on default branches
- non-indexed search exists as a fallback path for code that is not indexed
- searches scoped to specific repos are kept very fresh

Sources:

- https://sourcegraph.com/docs/admin/architecture
- https://sourcegraph.com/docs/admin/search
- https://sourcegraph.com/docs/code-search/features

What this means:

- a hybrid indexed + non-indexed fallback pattern is a proven architecture
- this is useful for Product 1 because some evidence may be missing from the index or may arrive faster than reindexing

### Sourcebot

Sourcebot is the most relevant modern product reference because it exposes indexed code search directly to agents and MCP clients.

Important official capabilities:

- `search_code`: substring or regex over indexed code
- `read_file`
- `list_tree`
- `list_commits`
- `ask_codebase`: an AI agent that uses search and code navigation tools
- branch / tag / commit-aware search
- query language with repo/language/file filters and boolean logic

Sources:

- https://docs.sourcebot.dev/
- https://docs.sourcebot.dev/docs/features/search/overview
- https://docs.sourcebot.dev/docs/features/search/syntax-reference
- https://docs.sourcebot.dev/docs/features/mcp-server
- https://docs.sourcebot.dev/docs/features/ask/overview

What this means:

- Sourcebot is very close to the evidence retrieval shape we want
- it separates:
  - exact indexed search
  - file/navigation tools
  - agentic codebase Q&A
- this is the clearest real-world pattern for Product 1 evidence retrieval

---

## 5. What Claude Code tells us

Claude Code’s official docs do **not** describe a dedicated semantic code index or a special “semantic grep” engine.

What the docs do show:

- built-in tools include `Glob`, `Grep`, `Read`, `LS`, `Bash`, and `Task`
- `ripgrep` is usually included and is part of search functionality
- Anthropic describes Claude Code as using **agentic search** to understand the codebase

Sources:

- https://docs.anthropic.com/en/docs/claude-code/settings
- https://docs.anthropic.com/en/docs/claude-code/setup
- https://www.anthropic.com/claude-code

This suggests the following interpretation:

- Claude Code’s “smartness” is mainly in **planning and iterating over search tools**
- not in a hidden dedicated semantic grep index

This is an inference from the official docs, not an explicit quoted statement.

### What Claude Code is actually strong at

Claude Code is strong at:

- deciding what to search for next
- broadening or narrowing grep queries
- following up a grep with file reads
- spawning subagents for exploration
- mixing shell tools, code reads, and planning

That is exactly the kind of orchestration behavior we should borrow.

### What Claude Code is not

Claude Code is not, by itself:

- a centralized multi-repo evidence index
- a stable retrieval API for exact evidence across an enterprise
- a replacement for a dedicated exact search layer

So when people say Claude Code does “smarter grep,” the best technical interpretation is:

**agentic grep orchestration**

not:

**a semantic retrieval engine that replaces exact index search**

---

## 6. Is there a place for semantic retrieval here?

Yes, but narrow.

A small semantic layer can help with:

- service alias lookup
- docstring / README discovery
- synonym expansion
- query rewriting hints

But that should sit above or beside the exact index, not replace it.

For Product 1 evidence retrieval, the priority is still:

- exact match
- regex
- symbol and structural lookup
- repo/file/ref filtering

---

## 7. Recommended architecture for evidence retrieval

## Layer 1: Exact index backbone

Capabilities:

- substring search
- regex search
- boolean query support
- repo/language/file filters
- branch / tag / commit awareness
- code-aware ranking

Best reference pattern:

- Sourcebot on top of Zoekt

### Recommended stance

- do **not** build a search engine from scratch
- either:
  - build on top of Zoekt directly, or
  - build on top of Sourcebot if its API/tooling shape fits our system

## Layer 2: File and navigation evidence APIs

Capabilities:

- read file by repo/path/ref
- list tree
- list commits
- eventually symbol refs/defs where available

This is essential because search results alone are not enough for good evidence retrieval.

## Layer 3: Query planner / agentic search behavior

Capabilities:

- rewrite vague queries into exact searches
- expand or narrow grep/index queries
- choose which evidence tool to call next
- follow search with read/list/commit tools
- merge evidence from multiple searches

Best reference pattern:

- Claude Code’s agentic search behavior

### Important point

The agent should orchestrate the evidence layer.

It should **not** replace the evidence layer.

## Layer 4: Optional fallback path

Like Sourcegraph’s non-indexed search path:

- if a repo/ref/file is not indexed yet
- or freshness matters more than index lag
- or a niche search case falls outside the index

then fall back to:

- direct grep
- direct file system reads
- repo-native search commands

This is a practical reliability feature.

---

## 8. Recommended product behavior

For Product 1, the evidence retrieval layer should behave like this:

### Exact by default

Use the exact index first for:

- identifiers
- endpoints
- topic names
- config keys
- manifest fields
- protocol strings

### Agentically guided

Use an agent/planner to:

- decompose natural language into evidence searches
- choose search scopes
- decide when to read files
- decide when to stop

### Not embeddings-led

Do not answer code evidence questions by semantic similarity first.

### Ref-aware and provenance-preserving

Every evidence result should preserve:

- repo
- path
- ref/branch/commit
- line/snippet where possible

That is a core requirement, not a nice-to-have.

---

## 9. Practical recommendation

If choosing today, the best evidence retrieval direction is:

### Preferred architecture

- **Exact index substrate:** Zoekt or Sourcebot-backed indexed search
- **Agentic retrieval behavior:** Claude Code-style planner over search/read tools
- **Fallback path:** direct grep/read when the index is stale, missing, or insufficient

### If we want the fastest path

Start by evaluating whether Sourcebot can be:

- used directly
- forked
- or used as a behavioral benchmark

because it already bundles:

- indexed code search
- MCP tool exposure
- file reads
- natural-language codebase Q&A

### If we want the cleanest custom control

Use Zoekt as the search substrate and build our own evidence APIs and orchestration layer on top.

This is more work, but cleaner for long-term product control.

---

## 10. Final recommendation

Build the Product 1 evidence retrieval layer as:

**Sourcebot/Zoekt-style exact indexed retrieval, orchestrated with Claude Code-style agentic search behavior.**

Not:

- pure grep
- pure semantic code search
- pure agent-over-files without an index

The simplest summary is:

**Be Sourcebot underneath, be Claude-like in how you drive it.**

---

## 11. Sources

- Sourcebot overview  
  https://docs.sourcebot.dev/
- Sourcebot code search overview  
  https://docs.sourcebot.dev/docs/features/search/overview
- Sourcebot search syntax  
  https://docs.sourcebot.dev/docs/features/search/syntax-reference
- Sourcebot MCP server  
  https://docs.sourcebot.dev/docs/features/mcp-server
- Sourcebot Ask overview  
  https://docs.sourcebot.dev/docs/features/ask/overview
- Zoekt repository README  
  https://github.com/sourcegraph/zoekt
- Sourcegraph architecture  
  https://sourcegraph.com/docs/admin/architecture
- Sourcegraph search configuration  
  https://sourcegraph.com/docs/admin/search
- Sourcegraph code search features  
  https://sourcegraph.com/docs/code-search/features
- Claude Code overview  
  https://docs.anthropic.com/en/docs/claude-code/overview
- Claude Code settings  
  https://docs.anthropic.com/en/docs/claude-code/settings
- Claude Code setup  
  https://docs.anthropic.com/en/docs/claude-code/setup
- Claude Code product page  
  https://www.anthropic.com/claude-code
