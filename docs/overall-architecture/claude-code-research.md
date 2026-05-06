# Code Search Research — SuperContext Product 1

**Status:** Research findings + recommendation
**Date:** 2026-04-27
**Scope:** Evaluate code-search foundations for Product 1 (typed cross-service graph for AI coding agents). Inputs from four parallel research agents covering OSS engines, agentic-LLM search, embedding/RAG, and code-graph systems.

---

## 1. TL;DR

**Build a typed cross-service graph as the spine. Use agentic search (Claude Agent SDK) as the ingestion engine and gap-fill explorer. Skip code-chunk embeddings; use embeddings only on prose surfaces (READMEs, ADRs, event docstrings) for semantic alias resolution.**

The PRD's defensible wedge — async/event edges, schema lineage, deploy topology, cross-repo blast radius, refusal-on-uninstrumented — is exactly the query class where text search and code embeddings fail and a typed graph wins. Three independent industry signals converge on this conclusion:

1. **Sourcegraph deprecated embeddings** in Cody Enterprise once their structural graph was good enough.
2. **Anthropic dropped RAG** for Claude Code in favor of grep + read tool loops.
3. **Bloop archived (Jan 2025); Sweep pivoted away.** The embedding-only PR-bot wedge died in market.

The shortest articulation: *agentic search is a great way to build and patch the graph; it is not a great way to be the graph.*

---

## 2. Three approaches surveyed

| Approach | Canonical example | What it does well | What it fails at |
|---|---|---|---|
| **Index-based code search (trigram / AST)** | Zoekt, Sourcebot, ast-grep, Semgrep | Fast literal + regex + structural queries within a repo or fleet | Cross-repo identity, runtime topology, schema lineage, blast-radius reasoning |
| **Agentic search (grep + read in a loop)** | Claude Code, Aider, Sourcegraph Amp, Cursor agent mode | Always fresh, exact identifier matches, simple security model, fails loudly | High latency (~90 tool calls / 1M tokens per task), can't see across repos cheaply, can't see runtime/delivery edges |
| **Code graph (typed nodes + edges with provenance)** | SCIP, Glean (Meta), Stack Graphs, Multiplayer.app | Deterministic answers to "who calls X", "consumers of topic Y", "blast radius of diff Z"; auditable; refusable | Up-front ingestion cost; staleness if not maintained; doesn't help with fuzzy/conceptual queries |
| **Embedding / RAG** | Cursor index, Greptile, Continue, Cody (deprecated) | "Where do we handle webhooks?" / fuzzy semantic intent / NL→service alias | Identifier imprecision, silent wrong answers, staleness, no provenance, dilution at scale |

---

## 3. OSS code-search landscape (per-tool)

### Live and relevant
- **Sourcebot** (MIT, sourcebot.dev). Embedded Zoekt + first-class MCP server (`search_code`, `read_file`, `glob`, `list_tree`, refs/defs). Multi-host (GitHub/GitLab/Bitbucket/Gitea/Gerrit). Newest, most agent-native OSS code search. **Closest to a build-on-top candidate** if we want to skip rebuilding text search.
- **Zoekt** (Apache 2). Positional trigram index. Powers Sourcegraph.com and Sourcebot. Google archived March 2025; Sourcegraph is now official maintainer. Don't use raw — wrap.
- **ast-grep** (MIT). Tree-sitter CST patterns in host-language syntax. ~30 languages. Has experimental MCP server. Right primitive for structural call-site detection. No global index, single-repo focus.
- **Semgrep OSS / Opengrep**. Engine LGPL 2.1 (still OSS). Rules repo relicensed Dec 2024 (non-compete) → **Opengrep fork** (Feb 2025) is the truly OSS path forward. Use for framework-aware call-site rules (HTTP/gRPC/Kafka).
- **ripgrep** (MIT/Unlicense). The default search inside Claude Code, Cursor, every agent shell. Right baseline for ad-hoc; wrong primary engine for enterprise-scale SaaS.

### Effectively dead or wrong-fit
- **Sourcegraph OSS.** License changed June 2023 (Apache → Enterprise); main repo went private Aug 2024. The still-OSS pieces (Zoekt, SCIP indexers, Cody) are better consumed directly. Don't build on the closed product.
- **OpenGrok** (CDDL, Java). Alive but niche (kernel/OS-vendor tool). Awkward license, dated UX.
- **Hound, livegrep** (MIT/BSD). Maintained, niche. Sourcebot has the same niche with momentum.
- **Universal Ctags / GNU Global.** Cheap fallback symbol indexers; ctags only is enough for long-tail languages.

### Newer agent-era entries worth tracking
- **CocoIndex Code** (Apache 2). Rust + tree-sitter + local embeddings + MCP. Validates the "AST-chunked + local embeddings" pattern.
- **Claude Context** (Zilliz/Milvus). Vector-DB-heavy MCP server for Claude Code.

**Recommendation:** Build on top of Zoekt for text search (or fork Sourcebot if MCP shape is right). Use ast-grep + Opengrep rules for structural call-site detection. Use ripgrep as in-process fallback. Ingest from SCIP indexers for symbol-level edges per language.

---

## 4. Agentic search — what Claude Agent SDK gives us

The Claude Agent SDK packages Claude Code's tool loop as an importable library (Python + TypeScript). Concrete deliverables out of the box:

- **Tool suite as primitives:** `Read`, `Glob`, `Grep` (ripgrep-backed), `Bash`, `Edit`, `Write`, `Monitor`, `WebSearch`, `WebFetch`, `Agent` (subagent invocation), `AskUserQuestion`. Read-only tools execute concurrently; mutating tools serialize.
- **MCP as first-class consumer.** Our SuperContext MCP slots in alongside built-in tools. The agent decides when to call us vs. when to grep — the same pattern Cursor and Amp use.
- **Hooks** (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`) — natural place for `last_indexed_at` checks, audit logs, permission denials.
- **Subagents with isolated context windows.** Mirror Claude Code's `Explore` pattern: a `graph_explorer` subagent talks to our MCP and returns a summary; main agent stays clean.
- **Session resume/fork** — IDE / PR-bot / CLI surfaces can share context.
- **Provider-agnostic:** Anthropic API, Bedrock, Vertex, Foundry. Caching + Haiku-for-subagents are the cost levers. Real-world coding tasks consume 200k–1M input tokens; budget accordingly.

### Where agentic search shines for SuperContext
- **Ingestion-time graph builder.** Spin up a Claude Agent SDK worker per repo to *build* the graph: find call sites, resolve client SDK aliases, normalize topic names, identify dynamic consumer registrations. This is exactly the fuzzy work where grep + LLM reasoning beats hand-tuned Semgrep rules.
- **Coverage gap recovery.** When the graph returns "uninstrumented for this edge," dispatch an agentic explorer; surface result with `evidence: "agentic", confidence: "low"`.
- **Long-tail conceptual queries** the graph doesn't model ("what's the convention for retry logic in this org?").

### Where agentic search alone breaks Product 1
1. **Async/event edges.** Topic names live in config, env vars, runtime `subscribe()` calls, codegen. Grep gives silent false negatives. Confidence-bounded liar on the canonical wedge query.
2. **Cross-repo blast radius.** 50 services × thousands of files each = 30+ second tool latency, 100k+ tokens per query. PR-bot economics don't work.
3. **Runtime + delivery edges.** OTel traces, Helm/k8s topology, feature-flag dependencies are not in the source code. No amount of grep finds them.
4. **Provenance + refusal.** PRD §6.4 mandates `last_indexed_at` and "refuse when uninstrumented." Agentic search has no notion of "uninstrumented" — it just keeps grepping.
5. **PR-bot latency.** Maya's PR-time use case needs comments in seconds, not minutes-and-90-tool-calls.

**Recommendation:** Use Claude Agent SDK as ingestion engine + fallback explorer. Do not use it as the primary retrieval substrate.

---

## 5. Embeddings / RAG — verdict: skip code-chunk embeddings

### Industry trajectory
- **Cody Enterprise deprecated embeddings.** Replaced by structural graph + BM25. Cited reasons: code had to leave the box for embedding APIs, vectors were expensive at scale, poor recall beyond ~100k repos.
- **Cursor still embeds** (Turbopuffer + tree-sitter chunks, custom embedding model) but signals (Tigerdata, July 2025) suggest pivot to agentic after hiring two Claude Code leads.
- **Bloop archived Jan 2025.** Sweep pivoted to JetBrains autocomplete after the PR-bot wedge failed. The embedding-only generation died in market.
- **Anthropic** dropped RAG from Claude Code; Boris Cherny: "agentic search outperformed everything. By a lot."

### Failure modes for our wedge queries
- **Identifier imprecision.** `getUserById` ≈ `findUserByEmail` ≈ `updateUserProfile` in vector space. Code requires exact identifier matches.
- **No structural awareness.** Cannot follow `handler.ts → utils/auth.ts → lib/jwt.ts`. Cannot answer "what calls this exact function."
- **Silent wrong answers.** Grep fails loudly (no result); embeddings fail silently (wrong result with high confidence). For agents that act on retrieved context, silent failures are catastrophic.
- **No provenance.** "This fact came from line 47 of helm chart X" cannot be reconstructed from a cosine score. Incompatible with PRD §7's provenance-on-every-fact rule.
- **Dilution at scale.** Top-k dominated by near-duplicates (boilerplate, generated code, vendored deps) in 100k+ chunk repos.

### Where embeddings *do* add narrow value (~10-15% surface area)
1. **`search_services` semantic alias resolution.** "billing service" → `payments-svc` + `invoice-engine` + `dunning-worker`. Embed Service-node descriptions/READMEs.
2. **Schema/event semantic search.** "events about order cancellation" → `OrderCancelled` + `RefundRequested` + `ChargebackInitiated`. Embed event-name + event-doc.
3. **README / ADR / runbook surfaces.** Prose context the agent might want at PR-time or oncall.
4. **Re-ranking** secondary score on graph-traversal results.

**Recommendation:** Skip code-chunk embeddings entirely. Apply embeddings narrowly to three artifact types: Service descriptions, event/schema docstrings, ADRs/runbooks. Never as a foundation.

---

## 6. Code graph + cross-service prior art

### Build vs. buy vs. ingest matrix

| Layer | Recommendation | Best 1-2 sources |
|---|---|---|
| Static intra-repo symbols | **Ingest** | SCIP indexers (Apache 2) + Stack Graphs (MIT/Apache) for cross-file resolution |
| Static cross-service call graph (HTTP/gRPC sites) | **Build** | tree-sitter + ast-grep + Opengrep rules — no off-the-shelf option ingests OpenAPI/proto and matches them to call sites |
| Schema/contract layer (events) | **Ingest** | Confluent Stream Catalog API, Buf BSR, AsyncAPI files via EventCatalog |
| Runtime call graph | **Ingest** | OTel (Datadog Service Dependencies API, Honeycomb Service Maps API), Cilium Hubble for k8s |
| Deploy topology | **Build** | Lightweight Helm/k8s manifest parser — no off-the-shelf option unifies manifests + repo |
| Ownership / Owner edges | **Ingest** | Backstage YAML, Cortex/OpsLevel/Port/Compass APIs, CODEOWNERS as fallback |
| Fact storage / query engine | **Build-on-top** | Postgres + graph index for v1. Glean (Datalog) is plausible but Haskell + ops-heavy. Neo4j only if query patterns demand it. |

### Notable specifics
- **SCIP** (Apache 2). Replaced LSIF. Models symbols/defs/refs/occurrences/types within a repo. Indexers exist for Java/Scala/Kotlin, TS/JS, Rust, C/C++, Python, Ruby, .NET, Dart, PHP. Zero notion of cross-service edges — that's our job.
- **Glean (facebookincubator)** (BSD). Datalog-style fact store with extensible schema (Angle query language). Could be a graph-DB foundation, but Haskell core + narrow community + ops weight.
- **Stack Graphs** (MIT/Apache). Tree-sitter-based, file-incremental, language-agnostic name resolution. Powers GitHub Precise Code Navigation. Pairs well with SCIP.
- **Multiplayer.app** (closest direct competitor). Trace-first auto-architecture diagrams, full-stack session recordings, MCP for Claude Code/Cursor. Pricing $0–$250/mo published. Their graph is a runtime byproduct — they cannot answer "what tests must pass before this PR ships" because they don't ingest schemas, manifests, or ownership. **That's our seam.**
- **Backstage / Cortex / OpsLevel / Port / Compass.** Catalog data with `dependsOn` / `providesApi` / `consumesApi` / `ownedBy` edges. Ingest where present; never compete.
- **Cilium Hubble / Istio Kiali / Pixie.** eBPF-based runtime service maps. Strong signal, k8s-bound, complements OTel.
- **Schema registries** (Confluent Stream Catalog, Buf BSR, Apicurio, EventCatalog). Gold standard for event producer/consumer maps. Already exposed via REST APIs.

### Standards gap = opportunity
There is **no OpenLineage analog for service graphs.** OpenLineage covers data jobs/datasets/runs only. Closest "standards" are Backstage's entity model (de facto only in Backstage) and OTel Resource semantic conventions (describes a service but not edges). SuperContext could publish its schema as an open spec and become the OpenLineage of service graphs — a long-term defensibility move worth flagging.

### Genuinely novel in PRD
`FeatureFlag` / `gates` / `migrates_with` / `shares_db_with` are not modeled by any of the surveyed systems. These are tightly tied to the blast-radius use case and represent real white space.

---

## 7. Recommendation — Product 1 architecture

```
                        Surfaces
              MCP server | PR bot | CLI/REST
                              |
                              v
                  +-----------------------+
                  |  Query layer          |
                  |  (8 PRD tools)        |
                  +-----------------------+
                              |
                              v
       +-----------------------------------------------+
       |  Typed Service Graph (Postgres + graph idx)   |
       |  Provenance, last_indexed_at on every fact    |
       +-----------------------------------------------+
        ^   ^   ^   ^   ^   ^                       ^
        |   |   |   |   |   |                       |
   +----+-+ | +-+-+ | +-+--------+   +--------------+----------+
   | SCIP | | |Buf| | |Backstage |   | Agentic explorer        |
   | indx | | |BSR| | |Cortex API|   | (Claude Agent SDK)      |
   +------+ | +---+ | +----------+   | gap-fill + ingestion    |
        +---+   +---+                +-------------------------+
        |       |
   +----+--+ +--+--+
   | tree- | | OTel |
   | sitter| | APM  |
   | + Op- | | Hubble|
   | grep  | +------+
   +-------+
```

### What we build
1. **Graph schema and storage.** Postgres + a graph index for v1 (defer Neo4j unless query patterns force it). Provenance attached at fact level: `commit_sha + file:line` for code, `topic + schema_version + last_seen_at` for events, `trace_id + observed_at` for runtime edges.
2. **Static cross-service call detector.** tree-sitter for AST + ast-grep patterns + Opengrep rules per language for typed HTTP/gRPC clients (Retrofit, OpenAPI-generated SDKs, gRPC stubs). Bridges contracts to callers.
3. **Helm/k8s manifest parser.** Deploy topology + ConfigMap-injected URLs. Lightweight; no off-the-shelf option.
4. **MCP server with 8 PRD tools.** Streamable HTTP, OAuth 2.1.
5. **PR bot.** Read-only GitHub app; blast-radius comment from graph queries.
6. **Agentic ingestion worker.** Claude Agent SDK process per repo: find dynamic call sites, normalize topic names, resolve codegen aliases, identify consumer registrations grep can't see directly. Output is graph upserts with provenance.
7. **Narrow embedding layer.** Service-node descriptions + event docstrings + ADRs/runbooks only. Powers `search_services` semantic alias and ADR retrieval. Self-hosted embedder (nomic-embed-text via Ollama, or voyage-code-3 if cloud is acceptable).

### What we ingest (don't reinvent)
- **SCIP indexers** (Apache 2) for per-language symbol graphs.
- **Stack Graphs** for cross-file name resolution where SCIP doesn't reach.
- **OTel via Datadog Service Dependencies API / Honeycomb Service Maps API / Tempo / Jaeger** for runtime edges.
- **Cilium Hubble** for k8s runtime call graphs (when present).
- **Confluent Stream Catalog / Buf BSR / EventCatalog (AsyncAPI)** for event producer/consumer edges.
- **Backstage / Cortex / OpsLevel / Port / Compass** APIs for ownership and catalog metadata.
- **CODEOWNERS** as fallback for ownership.

### What we explicitly skip
- **Code-chunk embeddings.** Industry trajectory + provenance incompatibility + silent failure mode.
- **Building a text search engine from scratch.** Use Zoekt (or fork Sourcebot for MCP shape).
- **Reimplementing per-language symbol indexing.** SCIP is Apache 2; ingest it.
- **Trace ingestion infrastructure.** Use vendor APIs; don't run our own collector.
- **Service catalog / IDP layer.** Sit above; don't compete.

### What we maybe ingest from
- **Sourcebot** as a turnkey Zoekt + MCP. If their MCP shape matches our needs, fork or build-on-top to skip rebuilding text search. If not, use Zoekt directly.

---

## 8. Open questions

1. Postgres + graph index, or Glean/Datalog from day one? Postgres is faster to ship; Glean is closer to the long-term query model.
2. SCIP coverage — which language indexers are mature enough to depend on for the first design partner? (Maps to PRD §14 Q2: pick TS/JS, Go, or Java/Kotlin first.)
3. Sourcebot fork vs. clean Zoekt build — depends on whether their MCP tool shape matches our 8-tool surface or fights it.
4. Trace ingestion source for MVP — Datadog (largest enterprise footprint, weakest tail-read API), Tempo, or Jaeger? PRD §14 Q3 already flags this; design partner choice resolves.
5. Embedder hosting — self-host (operational tax, no code leaves box) vs. Voyage/OpenAI (faster, blocks regulated buyers)? Likely self-host from day one given fintech/health ICP.
6. Standards play — publish the graph schema as open spec ("OpenServiceGraph"?) early to box out Multiplayer/Sourcegraph from defining it? Or defer until two design partners.

---

## 9. Appendix — sources by agent

Detailed per-tool citations are in the four agent transcripts. Key URLs:

**OSS code search:** [Sourcebot](https://github.com/sourcebot-dev/sourcebot), [Zoekt](https://github.com/sourcegraph/zoekt), [ast-grep](https://ast-grep.github.io/), [Opengrep launch](https://www.infoq.com/news/2025/02/semgrep-forked-opengrep/), [Sourcegraph license change](https://devclass.com/2024/08/21/sourcegraph-makes-core-repository-private-co-founder-complains-open-source-means-extra-work-and-risk/)

**Agentic search:** [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Building agents with Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk), [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [Boris Cherny on agentic search](https://x.com/bcherny/status/2017824286489383315), [Aider repo map](https://aider.chat/2023/10/22/repomap.html), [Amp manual](https://ampcode.com/manual)

**Embeddings/RAG:** [How Cody understands your codebase](https://sourcegraph.com/blog/how-cody-understands-your-codebase), [Why Cursor is about to ditch vector search](https://www.tigerdata.com/blog/why-cursor-is-about-to-ditch-vector-search-and-you-should-too), [Why grep beat embeddings (Augment)](https://jxnl.co/writing/2025/09/11/why-grep-beat-embeddings-in-our-swe-bench-agent-lessons-from-augment/), [Bloop archived](https://github.com/BloopAI/bloop), [CoIR benchmark (arXiv 2407.02883)](https://arxiv.org/html/2407.02883v1)

**Code graph + cross-service:** [SCIP](https://github.com/sourcegraph/scip), [Glean (Meta)](https://github.com/facebookincubator/Glean), [Stack Graphs](https://github.com/github/stack-graphs), [Multiplayer.app](https://www.multiplayer.app/), [Multiplayer pricing](https://www.multiplayer.app/pricing/), [Backstage Software Catalog](https://backstage.io/docs/features/software-catalog/), [Datadog Service Dependencies API](https://docs.datadoghq.com/api/latest/service-dependencies/), [Honeycomb Service Maps API](https://api-docs.honeycomb.io/api/service-maps), [Confluent Stream Catalog](https://docs.confluent.io/cloud/current/stream-governance/stream-catalog-rest-apis.html)
