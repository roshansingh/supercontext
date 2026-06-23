# SuperContext — Product Requirements Document

**Status:** Draft v0.1
**Author:** Roshan Singh
**Date:** 2026-04-27

---

## 1. One-liner

**SuperContext is the context backbone for AI coding agents in microservice organizations.** It builds and serves a unified, real-time graph of how services call, consume, share, and deploy with each other — so that when Claude Code, Cursor, or Copilot makes a change in service A, it understands the blast radius across services B through Z before the diff is even written.

This PRD defines **Product 1** of a broader SuperContext platform: the code and service-graph layer for engineering teams. The broader platform may later extend the same provenance-first model to docs, tickets, files, and other enterprise systems, but those are intentionally out of scope here.

---

## 2. Problem statement

In organizations with 50+ interdependent microservices, AI coding agents are systematically blind to the most expensive class of failure: changes that are locally correct but globally broken.

A change in service A passes A's local tests, ships through review, and lands in production — and then breaks service B's deserializer, takes a Kafka consumer offline, or trips a deploy gate in service C. The agent never had a chance, because nothing in its context window described the graph.

This is not a hypothetical. Five pieces of public evidence anchor the problem:

1. **DORA 2024** — Google's State of DevOps found that increased AI-tool adoption *correlated with decreased delivery throughput and stability* at the system level, even when individuals reported feeling faster. AI optimizes the local edit; the service graph pays the cost.
2. **METR 2025** — A randomized study of experienced open-source developers working on their own mature codebases found AI tools made them ~19% *slower*, while devs perceived a ~20% speedup. The illusion of speed is strongest precisely where context is weakest.
3. **GitClear 2024** — Code churn (lines reverted within two weeks) roughly doubled in AI-heavy codebases between 2022 and 2024. The signature failure: locally plausible code that doesn't survive contact with its consumers.
4. **Cortex IDP Report 2024** — The median enterprise with 1,000+ engineers operates 50+ microservices; the top quartile operates 500+. "Service ownership and dependency clarity" is the #1 reason orgs adopt internal developer platforms.
5. **Public postmortems** — Roblox's 73-hour 2021 outage (Consul config), Cloudflare Oct 2023, Rogers July 2022 — all share one structural pattern: a single, locally-reasonable change cascaded because the author lacked visibility into downstream consumers. AI agents are now making these kinds of changes autonomously, at volume.

The category is real, the gap is widening, and no tool today fills it.

---

## 3. Vision

SuperContext makes the service graph a first-class input to every AI coding interaction. Within three years, asking Claude Code or Cursor to "change this endpoint" without SuperContext in the loop should feel as reckless as deploying without tests.

In the broader company vision, this service graph is the first high-trust slice of a larger enterprise context layer. Product 1 earns the right to expand by solving engineering change-safety first.

---

## 4. Goals and non-goals

### Goals (v1)

- Reduce production incidents caused by AI-generated cross-service breakage
- Make blast-radius visible at three moments: in the IDE during edits, on PRs at review time, and in the terminal during oncall
- Reach context parity: the agent should know what a senior engineer who has worked on every service for two years knows
- Be IDP-agnostic: read whichever catalog the company already owns; don't force a migration
- Reach customer value within one week of installation (read-only Git access alone)

### Non-goals (v1)

- We are not a service catalog. We sit on top of Backstage/Cortex/OpsLevel/Compass; we don't compete with them.
- We are not an APM. We consume traces from Datadog/Tempo/Jaeger; we don't replace them.
- We are not an IDE. We feed Cursor/Claude Code/Copilot via MCP; we don't ship our own editor.
- We are not a code-generation model. We make existing models smarter; we don't train one.
- We are not a CI/CD platform.
- We are not, in v1, a general enterprise knowledge layer across Confluence, Jira, OneDrive, or SharePoint.

---

## 5. Personas and user stories

### Primary personas

- **Maya — Senior Backend Engineer (feature team).** Owns Checkout. Uses Cursor daily. Has shipped a quietly broken contract change at least once. Daily user.
- **Devraj — Platform / Infra Engineer.** Owns the schema registry and service templates. Quarterly migrator across 50+ services. Power user; champion buyer.
- **Priya — SRE / Oncall.** Diagnoses cross-service cascades at 3 AM. Episodic but high-stakes user.
- **Jordan — EM / Tech Lead.** Plans quarterly work, reviews PRs spanning teams. Episodic user; influencer in buying.
- **Lin — Security Engineer.** Drives auth/authz changes that fan across services. Episodic user.

### Buyer

VP Engineering or Head of Platform. They care about: (a) production incidents avoided, (b) PR cycle time, (c) new-hire ramp time, (d) ROI on existing AI tool spend. The pitch: *"SuperContext makes the Cursor and Copilot licenses you already pay for actually safe in your microservice org."*

### Anti-personas

Monolith shops, orgs <10 services, prototype teams, shops with no schema discipline (untyped REST + ad-hoc events). Value scales with service count and contract discipline.

### Top user stories (representative; full list in Appendix A)

1. **Maya / IDE-time.** When I ask my agent to remove a field from a public response, it enumerates every consumer and their parser strictness, and refuses without a deprecation path.
2. **Maya / PR-time.** Every PR I open gets an automatic blast-radius comment listing affected services, schemas touched, and which downstream consumers will deserialize-fail.
3. **Devraj / migration.** When I propose deleting a Kafka topic, my agent refuses unless it can prove zero consumers in the last 30 days of trace data.
4. **Priya / oncall.** When p99 spikes in cart-service, my agent diffs the call graph against one hour ago and surfaces new edges or upstream deploys.
5. **Jordan / planning.** I ask the agent for an "impact memo" on a proposed change and get affected services, owning teams, and historical incident links.
6. **New hire / onboarding.** Opening a service for the first time, my agent gives me "your 5 most important upstream deps and 3 noisiest downstream consumers."

---

## 6. Functional requirements

SuperContext is delivered through **three surfaces** backed by **one engine**.

For Product 1, that engine is intentionally limited to engineering-system sources. The broader platform can later add docs, tickets, files, and decision systems onto the same graph model.

### 6.1 The engine — multi-modal service graph

A typed graph with first-class node types: `Service`, `Endpoint`, `Event` (topic/subject), `Schema` (versioned), `Deploy`, `Repo`, `Owner`, `Database`, `FeatureFlag`. Edges encode `calls`, `produces`, `consumes`, `owns`, `gates`, `migrates_with`, `shares_db_with`, with metadata: traffic volume, last-seen-at, source provenance.

**MVP ingestion sources (5)** — one integration: read-only Git access — covers the first four:

1. **Git repos** — manifests, CODEOWNERS, IaC. Service inventory, ownership, deploy topology.
2. **API specs** — OpenAPI/Swagger, gRPC `.proto`, GraphQL SDL, AsyncAPI. The producer-side contract layer.
3. **Static call-site detection** — tree-sitter + Semgrep rules per language for typed HTTP/gRPC clients (Retrofit, OpenAPI-generated SDKs, gRPC stubs). Bridges contracts to callers without runtime.
4. **Kubernetes / Helm manifests** — deployment topology and ConfigMap-injected URLs (the declarative edge nobody mines).
5. **Distributed tracing** — OTel-compatible (Jaeger, Tempo, Datadog APM). The runtime ground truth that catches what static analysis misses and ranks edges by actual traffic.

The wedge insight: static sources tell you what's *possible*; tracing tells you what's *actual*. Both in the MVP is what separates SuperContext from a glorified `grep`.

**Provenance is non-negotiable.** Every fact returned by the engine carries `commit_sha + file:line` (for code) or `topic + schema_version + last_seen_at` (for events). Without this, agents will rephrase stale facts confidently and erode trust in one bad week. (See Glean and Cody Enterprise for prior art.)

### 6.2 Surface 1 — MCP server (primary)

One server, written once, reaches Claude Code, Cursor, Continue, Cody, Zed, Windsurf, JetBrains AI Assistant, and Copilot in VS Code. Streamable HTTP transport, OAuth 2.1 (or static bearer for self-hosted).

**MVP tool set (~8 tools, deliberately small).** Tools the model sees, with tight JSON schemas:

| Tool | Purpose |
|---|---|
| `search_services` | Find services by name, owner, or tag |
| `get_service_brief` | One-page neighborhood map for a given service (push-style, cacheable) |
| `find_callers` | Who calls this endpoint/method, with traffic + parser strictness |
| `find_callees` | What this service calls, with versions |
| `get_event_consumers` | Consumers of a Kafka topic / event subject, with last-seen-at |
| `get_event_producers` | Who publishes this event, with schema version |
| `blast_radius` | Given a diff or PR URL, return affected services, schemas, deploys |
| `deploy_blockers_for` | What must ship before/after a service can deploy |

**Resource:** `supercontext://service/{name}/brief` — a small (~2KB) push-attachable brief the IDE auto-attaches when the user opens a file in that service. This is the prompt-cache-friendly surface.

Response shape: structured JSON with stable IDs, depth limits (default `depth=1`, agent requests expansion), cursor pagination, summary-then-drill-down for any neighborhood >10 nodes.

### 6.3 Surface 2 — PR bot (highest credibility)

A GitHub / GitLab app that posts a "blast radius" comment on every PR touching a public contract: affected services, schemas changed, downstream consumers, parser strictness, prior incidents in adjacent code paths. Read-only. Zero workflow change. Lands credibility within a week of install — this is the wedge that turns into trust that turns into MCP adoption.

### 6.4 Surface 3 — CLI + REST

A thin CLI (`supercontext callers payments.charge`) and underlying REST API. ~1 day of work once the engine exists. Useful for:

- Shell-based agents (Claude Code subagents, custom scripts)
- Oncall humans grepping the graph at 3 AM
- CI gates beyond the PR bot (e.g., release-train sequencing)

**Explicitly deferred:** a bespoke IDE extension. MCP coverage in every major IDE (early 2026) makes this redundant for the MVP.

---

## 7. UX principles

- **Provenance on every fact.** Citations are not optional. If we can't cite it, we don't say it.
- **Small surface, high signal.** Eight tools, not eighty. Each tool's description is one paragraph the model actually reads.
- **Pull by default, push for orientation.** Agents pull on demand via tool calls; the IDE auto-pushes one small `service_brief` when a file opens. No giant context dumps.
- **Stale-aware.** Every response carries `last_indexed_at`. The agent (or the human) gets to decide if it's fresh enough.
- **Refuse when unsafe.** `blast_radius` and `deploy_blockers_for` should be willing to return *"I don't know — this part of the graph is uninstrumented"* rather than guess. False confidence is worse than absence.

---

## 8. Architecture (high level)

```
[Customer's repos / k8s / OTel / catalog]
                    |
            (read-only ingestion)
                    |
                    v
   +-----------------------------------------+
   |  Ingestion workers (per-source)          |
   |  - Git, OpenAPI/proto, tree-sitter,      |
   |    Helm/k8s, OTel trace tail             |
   +-----------------------------------------+
                    |
                    v
   +-----------------------------------------+
   |  Service Graph (typed, versioned)        |
   |  Postgres + graph index; provenance      |
   |  attached at fact level                  |
   +-----------------------------------------+
                    |
        +-----------+-----------+
        v           v           v
   [MCP server] [PR bot]   [CLI / REST]
        |           |           |
        v           v           v
   Claude Code   GitHub      humans, agents
   Cursor        GitLab      CI gates
   Copilot
   Continue
   ...
```

Deployment shapes: SaaS (multi-tenant, region-pinned) for v1; self-hosted Docker/Helm for security-conscious customers from v2 (this is table stakes for fintech/health).

Security posture: read-only on customer infra. No code leaves the customer environment in self-hosted mode. SSO/SCIM on day one for the SaaS plan.

---

## 9. MVP scope and non-MVP scope

### In MVP (target: 12 weeks to first paying design partner)

- Git ingestion (manifests, CODEOWNERS, OpenAPI/proto/GraphQL)
- Tree-sitter/Semgrep call detection for the top 3 languages by ICP signal (TS/JS, Go, Java/Kotlin)
- Helm/k8s manifest ingestion
- OTel trace ingestion (one source: Datadog *or* Tempo *or* Jaeger — pick based on first design partner)
- Service graph storage with provenance
- MCP server with the 8 tools above
- GitHub PR bot with blast-radius comment
- SaaS hosting, single-region, SSO

### Explicitly out of MVP

- Service mesh / eBPF ingestion
- Kafka schema registry deep integration (manual ingestion only)
- Database-coupling / shared-DB analysis
- Feature-flag / deploy-gating analysis
- Self-hosted deployment
- Auto-PR generation for migrations
- IDE-native UI (rely on MCP host UIs)
- Languages beyond TS/JS, Go, Java/Kotlin

---

## 10. Roadmap

**Phase 1 — Land (months 0-3): PR bot + MCP server.**
Read-only, single design partner. Win on credibility per dollar.

**Phase 2 — Expand (months 3-9): pre-merge gates, deprecation campaigns, self-hosted.**
Add async/event ingestion (Kafka schema registry, AsyncAPI), feature-flag and deploy coupling, more languages, self-hosted Helm chart.

**Phase 3 — Compound (months 9-18): agent-driven cross-repo migrations.**
Generate per-service migration PRs across the graph; integrate with release trains; add eBPF/mesh ingestion for tracing-thin customers.

---

## 11. Success metrics

### Leading indicators (weekly)

- MCP tool calls per active developer
- PR bot comments posted vs PRs that touch contracts (coverage)
- % of comments where the user clicks through to a cited source (trust)
- Time-to-first-value (install → first useful blast-radius comment)

### Lagging indicators (quarterly)

- Cross-service incidents per quarter (customer-reported, ideally tied to PR-bot-flagged-but-merged-anyway)
- PR review cycle time on cross-team PRs
- New-hire ramp time to first safe production change
- Net revenue retention; seat expansion within accounts

### North-star metric

**Cross-service incidents avoided per quarter, attributable to SuperContext** (measured via flagged-PR cohort vs control). This is the metric the platform leadership buyer cares about.

---

## 12. Competitive positioning

| Category | Examples | How they relate |
|---|---|---|
| Service catalogs / IDPs | Backstage, Cortex, OpsLevel, Port, Compass | **Complement.** We sit on top and ingest. We do not compete; we make their data agent-consumable. |
| AI dev tools | Cursor, Claude Code, Cody, Copilot, Continue | **Hosts.** They are our distribution. MCP is the API. |
| Code-graph search | Sourcegraph, Cody Enterprise | **Partial overlap.** They model code-call edges. We add runtime, events, deploy, schema-version edges. |
| Observability | Datadog, Lightstep, Honeycomb | **Data sources.** Their traces feed us. Their UIs are ops-time; ours is coding-time. |
| Closest direct competitor | **Multiplayer.app** | Auto-doc plus MCP from traces. Strong on runtime, weaker on schema/deploy/event coupling. We win by being multi-modal and IDP-agnostic. |

**Defensible white space:** fuse static + runtime + delivery into one graph; ship coding-time MCP rather than ops-time dashboards; own async/event edges no one else models; sit *above* the catalog war.

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Trace data is sparse or missing in the customer's stack | Ingestion is layered: Git-only customers still get value from contracts + static call detection. Tracing is a multiplier, not a prerequisite. |
| Hallucinated context erodes trust permanently | Citations on every fact. `last_indexed_at` on every response. Refuse to answer when uninstrumented. |
| Multiplayer.app or Sourcegraph ships our wedge first | Speed; depth on event/deploy/schema edges they don't model; IDP-agnostic ingestion; PR bot as a credibility wedge that locks in a workflow. |
| MCP loses to a proprietary spec (Cursor or GitHub forks the protocol) | Adapter layer behind the engine; CLI + REST surface independent of MCP; OpenCtx as a fallback. |
| Buyers say "we already have Backstage" | Position explicitly as the AI-context layer *over* Backstage. First-call demo: install on a real repo, show what their existing catalog *can't* tell their AI agent. |
| Selling into 50-service shops requires a long sales cycle | Bottoms-up via the IDE (free MCP server for the first repo) plus per-seat pricing for the platform team. PR bot is the wedge. |
| Privacy / IP concerns block adoption | Self-hosted Helm chart by Phase 2. Read-only on customer infra. SOC 2 Type 1 within 12 months. |

---

## 14. Open questions

1. **First-language priority.** TS/JS, Go, Java/Kotlin all matter. Which does the design partner run? Pick the one that gives us the cleanest demo for inbound prospects.
2. **Tracing source for the MVP.** Datadog has the largest enterprise footprint but the weakest API for high-volume tail-reads; Tempo and Jaeger are easier. Do we pick one or build all three?
3. **Pricing model.** Per-seat (matches Cursor/Copilot mental model), per-service (matches Backstage), or platform-team flat fee? Likely a hybrid; defer until two design partners are using it.
4. **Self-host vs SaaS-first.** Some logos won't sign for SaaS at all. Do we accept losing them in v1 to move faster, or invest in self-host from week one?
5. **Buyer entry point.** Is the first sale to the platform team (longer sales cycle, larger deal) or bottoms-up to a single feature team (faster, smaller, must convert later)?
6. **Where does training data go?** Customers will ask. Pre-commit to "we don't use your code or graph for model training, ever" or stay flexible?

---

## 15. Appendix A — extended user stories

1. Maya removes a response field; agent refuses without a deprecation plan.
2. Devraj proposes deleting a Kafka topic; agent demands proof of zero consumers in last 30 days.
3. Priya hits a p99 spike; agent diffs the call graph and surfaces an upstream deploy.
4. PR reviewer staring at a 600-line gRPC change gets a one-paragraph downstream-impact summary.
5. Jordan asks for a quarterly impact memo across 4 services.
6. New hire opens an unfamiliar service; agent surfaces the 3 noisiest consumers.
7. Lin changes an authz claim shape; agent enumerates every direct reader.
8. AI-generated PR passes local tests; pre-merge gate runs downstream consumer contract tests; reports a deserialization break before merge.

## 16. Appendix B — research basis

Five parallel research agents informed this PRD on 2026-04-27:
- Competitive landscape (IDPs, AI dev tools, code-graph, observability, MCP servers)
- Data sources (static, code analysis, runtime, async, org/process, deploy)
- Agent context delivery (MCP, retrieval patterns, formats, trust)
- Personas and workflows (5 personas, 8 user stories, adoption path)
- Evidence (DORA 2024, METR 2025, GitClear 2024, Cortex IDP, public postmortems)

Detailed findings available on request.
