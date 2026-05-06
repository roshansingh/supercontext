# DeepWiki Analysis — Claude

- **Status:** Research note, complementary to `DEEPWIKI-OSS-ANALYSIS.md`
- **Date:** 2026-05-01
- **Author:** Claude
- **Purpose:** Cover the parts Codex's note doesn't — the **hosted DeepWiki product surface** (Cognition's `mcp.deepwiki.com`), strategic/GTM observations, and a few specific borrow candidates not in the OSS analysis.

---

## 1. Scope and complementarity

Codex's `DEEPWIKI-OSS-ANALYSIS.md` covers the open-source variants (`AsyncFuncAI/deepwiki-open`, `AIDotNet/OpenDeepWiki`) at code-level depth, with a strong borrow/reject matrix and ADR mapping. That analysis is treated as the baseline here, not re-litigated.

This note focuses on five areas Codex's coverage didn't reach:

1. **Cognition's hosted DeepWiki MCP server** at `mcp.deepwiki.com` — different shape from the OSS variants
2. **Configuration-file pattern (`.devin/wiki.json`)** — customer-defined steering, missed in OSS analysis
3. **DeepResearch 5-iteration ceiling** — one concrete data point for ADR-0005 Tier 3 budget that was left unspecified
4. **Strategic / GTM lens** — hosted MCP as viral acquisition channel; relevance to SuperContext's PR-bot wedge
5. **Cross-product complementarity** — could SuperContext *generate* a DeepWiki-style narrative as a Phase 2/3 surface over its own graph?

---

## 2. Cognition's hosted DeepWiki MCP — surface analysis

DeepWiki ships a free hosted MCP server at `https://mcp.deepwiki.com/mcp`. Three tools, no authentication required for public GitHub repos.

| Tool | Purpose | Shape (inferred) |
|---|---|---|
| `read_wiki_structure` | Get topic listings for a repo | Tree of pages; analogue of SuperContext `get_service_brief` for repo scope |
| `read_wiki_contents` | View documentation pages | Markdown/HTML body for a page; no SuperContext analogue (we serve graph data, not prose docs) |
| `ask_question` | AI-powered Q&A | Natural-language tool; no SuperContext analogue (our 8 tools are all structured) |

**Install pattern:** `claude mcp add -s user -t http deepwiki https://mcp.deepwiki.com/mcp`. One-line user install. Streamable HTTP transport. Deprecating SSE legacy.

### Comparison to SuperContext's MCP surface (ADR-0002)

| Axis | DeepWiki MCP | SuperContext MCP |
|---|---|---|
| Tool count | 3 | 8 |
| Transport | Streamable HTTP | Streamable HTTP (matches per ADR-0002) |
| Auth | None for public repos | OAuth 2.1 SaaS / static bearer self-hosted |
| Hosting | Hosted only at `mcp.deepwiki.com` | Customer-VPC self-hosted per `PRD.md` §8 no-egress |
| Granularity | Per-repo | Per-tenant (cross-service) |
| Response shape | Prose-with-citations (LLM-generated) | Structured JSON with stable IDs (per ADR-0002 §"Schema discipline") |
| NL-fallback tool | Yes (`ask_question`) | No |
| Tool schema discipline | Loose (free-form Q&A return) | Tight (`depth=1` defaults, cursor pagination, summary-then-drill-down) |

**Borrow:** the install one-liner pattern. Documenting `claude mcp add -s user -t http supercontext https://mcp.<customer>.supercontext.app/mcp` as the published install command would match user expectations from DeepWiki.

**Don't borrow:** the `ask_question` NL-fallback tool. It bypasses SuperContext's typed-graph discipline (ADR-0006) and refusal-on-uninstrumented (PRD §7). DeepWiki gets away with it because its substrate is RAG; SuperContext's substrate is a typed graph where loose NL queries undermine the trust posture.

---

## 3. `.devin/wiki.json` — customer-defined steering

DeepWiki lets customers commit a `.devin/wiki.json` file in their repo to steer wiki generation: page list, page purposes, repo-context notes (`repo_notes`). This is exactly the pattern ADR-0001 already endorses for Claude Agent SDK skills (`.claude/skills/`, `.mcp.json`, `CLAUDE.md`) — filesystem-driven config the customer ships with their repo.

### What SuperContext could borrow

A `.supercontext/config.json` (or similar) per repo / per service that customers commit, providing:

- **Service identity overrides** — when slug normalization or alias resolution gets the wrong answer, customer pins the canonical identity
- **Owner overrides** — when CODEOWNERS doesn't match service ownership (common in monorepos)
- **Manual relations** — operator-asserted edges that promote per ADR-0006 §6 `manual_override` derivation class
- **Coverage hints** — "this repo doesn't run traces, don't expect runtime evidence" → updates `coverage` table
- **Deferred-extractor opt-out** — "skip protobuf parsing in this repo, it's vendored"

This is a non-trivial product surface and probably belongs in the future Source Connector + Extractor ADR. Worth flagging now so that ADR doesn't reinvent the file format.

DeepWiki's limits (30 pages, 100 notes, 10K-char-per-note) are theirs to size for prose generation; SuperContext shouldn't borrow those numbers.

---

## 4. DeepResearch 5-iteration ceiling — data point for ADR-0005

DeepWiki-Open's "DeepResearch" feature does multi-turn investigation **up to 5 iterations** before returning. This is a concrete number from a comparable system.

ADR-0005 §"Mode B Tier 3" left numeric budget defaults explicitly unspecified ("this ADR does not set numeric defaults"). DeepWiki's 5-iteration ceiling is one data point for what a plausible v1 default could look like:

- DeepWiki: 5 iterations of LLM + RAG retrieval before stopping
- ADR-0005 Tier 3: budgeted Explorer subagent with `Glob`/`Grep`/`Read` tools

Different substrate (RAG vs agentic search) but similar shape: bounded multi-iteration with a hard ceiling. v1 default of **5 iterations** for SuperContext's Explorer subagent is a defensible starting point, with per-tenant override per ADR-0005's configurability rule. This becomes one input to the open follow-up #4 in ADR-0005 ("Define default agentic exploration budgets from measured latency and token data").

Not a binding decision — just the first non-arbitrary number we have in the corpus.

---

## 5. Strategic / GTM lens

Codex's note is purely technical. Worth flagging the strategic angle separately because it has product-roadmap implications.

### DeepWiki's distribution play

Cognition's free hosted MCP at `mcp.deepwiki.com` is a viral acquisition channel:

- One-line install in any Claude Code / Cursor session
- Free for all public GitHub repos
- No auth, no signup
- Pulls users into the Devin paid funnel for private repos

This is the **opposite** wedge from SuperContext's PR-bot strategy (per ADR-0002 alternatives + PRD §6.3). DeepWiki funnels via the IDE; SuperContext funnels via the GitHub PR comment.

### What SuperContext could learn

**A free-tier hosted MCP for OSS repos** is a viable additional wedge that doesn't compete with the PR-bot wedge:

- Pre-index the top 200 OSS service-graph-shaped repos (Kubernetes, Linkerd, Istio, Backstage itself, etc.)
- Free hosted MCP at `mcp.supercontext.app/oss` with no auth
- Customers who like it install the on-prem version for their private codebases

Risk: hosting OSS repo data in our infra means *we* run the no-egress chart, not the customer. Could partition: hosted = OSS only; private = customer VPC.

This is a strategic decision, not a technical one. Belongs in `PLATFORM-PRD.md` discussion or a separate GTM doc, not an ADR. Flagging here so it doesn't get lost.

---

## 6. Cross-product complementarity — can SuperContext *generate* a DeepWiki-style narrative?

Codex's note correctly says generated wiki docs are candidate/enrichment artifacts, not canonical facts (per ADR-0004). I want to push that idea one step further.

### The opportunity

SuperContext has the **better substrate** for a DeepWiki-style wiki than DeepWiki itself, because:

- **Typed service graph** (ADR-0006) gives structural input that DeepWiki has to infer from prose
- **Provenance-pinned evidence** (ADR-0005 Mode A) means every wiki sentence can cite `commit_sha + file:line` instead of LLM-summarized prose
- **Cross-service edges** (CALLS, PRODUCES, CONSUMES, DEPENDS_ON) let the wiki describe service interactions, not just per-service overview

A SuperContext-generated service wiki would be:

- More accurate (graph-backed, not prose-summarized)
- More auditable (provenance on every claim)
- Multi-service (DeepWiki is repo-bound)
- Refusable (says "uninstrumented" instead of guessing)

### Where it fits in the roadmap

This is a Phase 2/3 surface, not v1:

- v1 surfaces are MCP + PR bot + CLI/REST per ADR-0002 / PRD §6
- Phase 2/3 could add: **`get_service_wiki(service_id)` MCP tool** that returns a Markdown narrative generated from the typed graph + evidence layer, with Mermaid diagrams of the service neighborhood
- Generated wikis live in the candidate / enrichment sidecar (ADR-0004), not the canonical graph
- Each wiki page section cites underlying canonical facts via Entity URN or Fact ID

### Risk

If shipped early, "wiki" becomes the headline feature and the typed-graph differentiator gets lost in the perception that we're "the open-source DeepWiki." Don't ship until the typed graph is the proven substrate.

Worth discussing as a Phase 2 candidate in `PLATFORM-PRD.md` §11.

---

## 7. Mermaid in PR-bot blast-radius comments

Codex's borrow #8 mentions "Mermaid rendering and diagram UX" generically. Concrete recommendation:

The PR bot (per PRD §6.3) currently posts text-only blast-radius comments. Adding a **Mermaid graph diagram** showing the touched services + downstream consumers + parser strictness would:

- Land harder on PR reviewers (visual > text for graph topology)
- Match a UX pattern Cursor / Claude Code / GitHub users recognize (DeepWiki has trained the market)
- Stay within the typed-graph trust posture — the diagram is generated *from* canonical facts, not LLM-imagined

Implementation cost: Mermaid is text-format markdown that GitHub renders natively. The PR bot already has the graph data; rendering as Mermaid is straightforward.

Belongs in a future PR-bot ADR. Cheap, high UX impact.

---

## 8. Things Codex covered that I'd reinforce

- **Repository workspace abstraction + commit-delta processing** (Codex §"Concrete Borrow Candidates" High Value). This is the load-bearing OSS borrow. OpenDeepWiki's `RepositoryWorkspace` model is exactly what Layer A (per ADR-0001) needs as its per-repo state shape, and the changed-files diff lets coverage updates be incremental rather than full re-ingestion.
- **Processing state + per-step logs** (Codex §3 borrow). Goes directly into the future Observability / Operations ADR.
- **Reject embeddings-first** (Codex §"What We Should Not Borrow" #1). Aligned with ADR-0005 + overall-architecture research consensus. DeepWiki is the inverse architectural bet; reproducing it would undo the wedge.
- **Reject AI-generated diagrams as graph truth** (Codex §"Should Not Borrow" #6). Aligned with ADR-0004. Mermaid in PR-bot is OK *because* the graph is the source — the diagram is rendering, not data.

---

## 9. Net additions to Codex's note

| Add | Where it goes |
|---|---|
| Hosted MCP install one-liner pattern | Future Tool Query Contract ADR or MCP install docs |
| `.supercontext/config.json` per-repo customer steering | Future Source Connector + Extractor ADR |
| 5-iteration default for ADR-0005 Tier 3 Explorer budget | ADR-0005 follow-up #4 (start configurable, default 5) |
| Free hosted MCP for OSS repos as viral wedge | `PLATFORM-PRD.md` GTM discussion |
| Phase 2 `get_service_wiki()` MCP tool | `PLATFORM-PRD.md` §11 Phase 2 candidate |
| Mermaid in PR-bot blast-radius comments | Future PR-bot ADR |

None of these are blockers for v1. All are tracked items.

---

## 10. Sources

Same as Codex's note plus:

- DeepWiki hosted MCP docs: https://docs.devin.ai/work-with-devin/deepwiki-mcp
- DeepWiki product page: https://docs.devin.ai/work-with-devin/deepwiki
- DeepWiki marketing page: https://deepwiki.com/
- (Codex's note already cites the OSS repos at specific SHAs — see `DEEPWIKI-OSS-ANALYSIS.md` §11)

---

**Bottom line:** Codex's note is the binding technical analysis; this is the complement covering the hosted product surface, strategic angle, and a few additive borrow candidates. Together they cover both "what's in the OSS code" and "what Cognition's hosted product surface and strategy look like." Net: no new ADRs to land, but six tracked items for upcoming ADRs and product-strategy discussions.
