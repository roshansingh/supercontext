# Evidence Retrieval Research — SuperContext Product 1

> **RESOLVED — 2026-04-29.** The binding decision now lives in [`EVIDENCE-RETRIEVAL-RECOMMENDATION.md`](./EVIDENCE-RETRIEVAL-RECOMMENDATION.md) and [`../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`](../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md). This document is preserved as a research input; do not treat it as the final authority.

- **Status:** Recommendation
- **Date:** 2026-04-28
- **Authors:** Roshan Singh, Maruti Agarwal
- **Anchors:** `PRD.md` §6.1 (engine + provenance), §6.2 (MCP tools), §7 (UX — provenance, refusal), `adr/0001-claude-agent-sdk-for-internal-runtime.md`, `docs/agentic-layer/AGENTIC-LAYER-RECOMMENDATION-V2.md` §3 (Claude Agent SDK built-in tools), `docs/graph-building/claude-graph-building-research.md` §4 (Claude strict-mode tool use)

---

## 1. TL;DR + recommendation

**Build, don't buy Sourcebot. Use it as inspiration; vendor selectively.** Concrete picks:
- **Mode A — fetch-by-coordinate:** bare git via `go-git` (or `pygit2`) wrapped in a thin in-process content-addressed cache. Sourcebot's `read_file` works (it accepts a `ref` parameter), but it adds an HTTP+Zoekt hop you don't need when you already have `commit_sha + file:line`.
- **Mode B — search:** three-tier ladder — ripgrep (lexical) → ast-grep (structural) → Claude Agent SDK Explorer subagent (agentic "semantic grep"), in that order, gated by token/latency budgets.
- **Sourcebot verdict:** MIT, exposes the right MCP surface (`grep`, `glob`, `read_file`, `list_tree`, `find_symbol_definitions`, `find_symbol_references`, all with a `ref` parameter), and is a serious reference architecture. But it's a centralized index server. SuperContext's value is the **typed graph + provenance contract**, and the read layer should live next to the graph storage, not behind another HTTP service. Vendor the MCP tool definitions and query plans; don't depend on the daemon as runtime.

**The load-bearing finding on Claude Code:** "semantic grep" is **emergent, not a feature** — it's LLM reasoning over Glob/Grep/Read primitives, optionally inside the Explore subagent for context isolation. There is no embedding model, no vector DB, no learned retriever in the loop. We can reproduce this for SuperContext without any embedding infrastructure.

---

## 2. Mode A: Fetch-by-coordinate

You already have `commit_sha + file:line` from the graph. Three options.

**(a) Bare git via go-git / pygit2.** Open the bare repo, resolve `commit_sha → tree → blob`, slice lines `[L-N, L+N]`. Single syscall family, no daemon, no index. Sub-millisecond on a warm page cache. Returns the exact bytes Claude would have read. Cleanest match for the "commit-pinned, refuse on absence" PRD constraint.

**(b) Sourcebot `read_file` MCP tool.** Confirmed signature: `read_file(repo, path, ref?, offset?, limit?)`, where `ref` accepts "Commit SHA, branch or tag name." So commit-pinned reads work. Pros: free MCP wrapping, multi-repo routing already done. Cons: extra hop (your service → Sourcebot HTTP → git), opaque caching, you don't own the SLA, you're bound to its repo-id model. For PR-bot sub-second SLA this is borderline acceptable but suboptimal.

**(c) In-process content-addressed cache over git.** Same as (a) plus an LRU keyed on `(commit_sha, path, line_range)`. The cache is trivially correct because keys are immutable (commits don't change). Hit rate will be high since PR bots reread the same hunks across reviewers and across refresh cycles.

**Pick: (c).** It's (a) plus ~30 lines of cache code. Avoids the Sourcebot hop. Owns its own latency budget. Trivial to deploy in-VPC with no egress. Refusal-on-absence is a first-class return value.

---

## 3. Mode B: Three tiers of search

**Lexical (ripgrep / Zoekt / Sourcebot `grep`).** Regex-over-bytes, optionally trigram-indexed (Zoekt). Latency: tens of ms to ~200 ms cross-repo. Accuracy: perfect recall on exact identifier strings, low recall on conceptual queries. Token cost: low (you control top-k). **Use as default first hop** — code identifiers are highly distinctive (Augment / Jason Liu finding).

**Structural (ast-grep / Comby).** Tree-sitter-backed pattern matching: "find all calls to `fn($A, $B)` where `$A` is a literal." Latency: similar to ripgrep on a per-file basis, slower at repo scale. Accuracy: high precision on syntactic shapes (decorators, call sites, type aliases). Token cost: low. **Use when lexical returns >50 hits or hits non-code matches** (comments, docstrings, generated files).

**Agentic "semantic grep" (Claude Code-style).** LLM-driven loop over Glob → Grep → Read with refinement. Latency: seconds to tens of seconds. Accuracy: highest on conceptual queries ("where do we authenticate stripe webhooks") because the model reads context, follows imports, and refines queries iteratively. Token cost: highest by 2–3 orders of magnitude. **Use only when lexical + structural fail, or when the graph emits "uninstrumented" and the explorer must produce a typed upsert candidate.**

---

## 4. What Claude Code actually does — the load-bearing section

Definitive findings from Anthropic's engineering blog, vadim.blog, the Pragmatic Engineer Cherny interview, and the Augment / Jason Liu post:

- **No index, no embeddings.** *"Claude Code does not pre-index your codebase or use vector embeddings"* (vadim.blog). Boris Cherny: *"Early versions of Claude Code used RAG + a local vector db, but we found pretty quickly that agentic search generally works better."*
- **Tool surface:** **Glob** (path patterns, near-zero token cost), **Grep** (ripgrep-backed regex on contents), **Read** (file load with offset/limit), **Bash** (`head`/`tail` for slicing), **Explore subagent** (Haiku, isolated context, returns summaries not raw bytes).
- **Loop:** think → pick tool → execute → observe → refine → repeat. Glob narrows file space, Grep narrows content space, Read confirms.
- **"Semantic grep" is emergent, not a feature.** It's (a) LLM reasoning over (b) lexical/structural primitives, optionally inside (c) the Explore subagent for context isolation. No embedding model, no vector DB, no learned retriever in the loop. The "semantic" property comes from the model knowing what to grep for next based on what the previous grep returned.
- **Why it beats embeddings on code (consolidated):**
  1. **Specificity** — code identifiers are unique; exact match wins.
  2. **Freshness** — filesystem is the source of truth; no staleness.
  3. **Persistence compensates** — agents run multiple searches; a bad query just gets refined.
  4. **No infra** — no index sync, no permission-model collisions.
  5. **Token-budget legibility** — top-k regex hits is a knob; embedding similarity isn't.

The Anthropic blog frames this as "just-in-time retrieval … lightweight identifiers and dynamic loading" vs upfront embedding. Augment confirmed empirically on SWE-bench: *"embedding-based retrieval wasn't the bottleneck they expected … grep and find were sufficient."*

The Explore subagent uses Haiku in an isolated window with Glob/Grep/Read and returns summaries (vadim.blog). The Agent SDK exposes this pattern as `AgentDefinition` with `tools=["Read","Glob","Grep"]` and a parent `Agent` tool — directly usable as Layer B in ADR-0001.

---

## 5. Can SuperContext reproduce this?

Two paths, complementary:

**(a) Thin agentic-search MCP tool.** SuperContext exposes `sctx_search(query, repos, ref, mode=lexical|structural|agentic)` plus `sctx_read(commit_sha, path, line_range)`. The customer's coding agent (Cursor, Claude Code, etc.) drives the loop. Cheap to build. Zero server-side LLM cost. Works only if the calling agent is good enough — fine for Claude Code/Cursor users, weaker for PR bots that need a deterministic SLA.

**(b) Server-side Claude Agent SDK explorer.** SuperContext runs its own Layer B agent (per ADR-0001) with `query()` + `AgentDefinition` for the explorer subagent. Inputs: an "uninstrumented edge" from the graph. Outputs: a typed evidence bundle with `commit_sha + file:line` provenance and a candidate typed upsert. Higher latency, predictable cost, deterministic surface for the PR-bot path.

**When to use which:** (a) for live IDE agents where the user pays the token bill and wants direct control. (b) for PR-bot, scheduled instrumentation runs, and any path where SuperContext has the SLA contract. They share the same underlying Mode A/B primitives — only the loop driver differs.

---

## 6. Sourcebot fork vs build

**Don't fork. Vendor selectively.** Sourcebot's MCP tool surface (`grep`, `glob`, `read_file`, `list_tree`, `list_commits`, `find_symbol_definitions`, `find_symbol_references`, `get_diff`, all with `ref`) is exactly the right shape, and MIT licensure makes copying signatures legal and easy. But:
- Sourcebot is a centralized indexer + UI + auth + multi-tenant service. SuperContext doesn't need most of that.
- Customer-VPC-no-egress means you operate the daemon. That's a deployment surface you'd rather not own twice (graph + indexer).
- Your provenance contract (typed edges, refusal-on-absence) is upstream of search; Sourcebot doesn't help you emit upserts.

**Recommendation:** copy the MCP tool schemas. Implement them on top of (Mode A: bare-git cache) + (Mode B: ripgrep + ast-grep + Agent SDK explorer). If you later need cross-repo trigram acceleration, embed Zoekt as a library, not a service.

---

## 7. Hybrid retrieval — pseudocode

```
edge = graph.lookup(symbol, commit_sha)
if edge.evidence:                          # cited file:line
    return mode_a.fetch(edge.commit_sha, edge.file, edge.line, ctx=N)

hits = mode_b.lexical(query, repos, ref=commit_sha, k=20)
if not hits:
    hits = mode_b.structural(query, ...)
if not hits or low_confidence(hits):
    hits = mode_b.agentic_explorer(query, repos, ref=commit_sha)  # Layer B

emit_typed_upsert(hits)
return hits or REFUSE
```

---

## 8. Prompt-cache + citation contract

Every MCP response carries the provenance in a stable shape so prompt-cache prefix hits hold across calls:

```json
{
  "evidence": [
    {
      "repo": "...",
      "commit_sha": "...",
      "path": "...",
      "line_start": 42,
      "line_end": 58,
      "bytes": "...",
      "source_tool": "mode_a|ripgrep|ast-grep|explorer",
      "confidence": "exact|structural|agentic"
    }
  ],
  "absent": false,
  "refusal_reason": null
}
```

Cache discipline: put high-churn fields (bytes, hit list) at the **end** of the message, immutable schema/preamble at the start. Customer agent gets a stable JSON contract; cache hits compound across PR-bot iterations on the same SHA. `absent: true` is a first-class signal — never silently fall back to HEAD.

---

## 9. Open questions

1. **Repo storage model** — bare git mirrors per repo inside the SuperContext VPC, or proxy through customer's existing host (GitHub Enterprise, Bitbucket DC)? Affects Mode A latency by 10–100×.
2. **Cross-repo `commit_sha` semantics** — graph edges presumably pin per-repo SHAs; how is the multi-service "evidence at this point in time" set defined?
3. **Explorer write path** — does Layer B get write access to the graph, or only emit upsert proposals reviewed by a separate writer? ADR-0001 implies the latter — confirm.
4. **Budget ceiling per uninstrumented-edge resolution** — soft cap on tokens / wall clock before refuse-on-absence kicks in?
5. **Structural search scope for v1** — ship `ast-grep` in v1, or is lexical + agentic enough? Adds a tree-sitter dependency per language.

---

## 10. Sources

- [Sourcebot MCP server docs](https://docs.sourcebot.dev/docs/features/mcp-server)
- [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Vadim's blog — Claude Code Doesn't Index Your Codebase](https://vadim.blog/claude-code-no-indexing)
- [Jason Liu — Why grep beat embeddings in our SWE-Bench agent (Augment lessons)](https://jxnl.co/writing/2025/09/11/why-grep-beat-embeddings-in-our-swe-bench-agent-lessons-from-augment/)
- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Pragmatic Engineer — Building Claude Code with Boris Cherny](https://newsletter.pragmaticengineer.com/p/building-claude-code-with-boris-cherny)

---

**Bottom line:** "Semantic grep" is not a feature — it's an emergent property of LLM-over-grep. Reproduce it for SuperContext with bare-git fetch + ripgrep + ast-grep + Claude Agent SDK Explorer subagent. Sourcebot is a reference, not a runtime. The provenance contract (`commit_sha + file:line` + refusal-on-absence) is the load-bearing piece — every retrieval path must honor it.
