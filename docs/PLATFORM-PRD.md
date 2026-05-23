# SuperContext Platform — Product Requirements Document

**Status:** Draft v0.1
**Author:** Roshan Singh
**Date:** 2026-04-27

---

## 1. One-liner

**SuperContext is the enterprise context layer for humans and AI agents.** It builds and serves a unified, provenance-first graph across code, systems, docs, tickets, files, and ownership, so people and agents can make changes with the full company context instead of isolated fragments.

---

## 2. Problem statement

Enterprise knowledge is fragmented across systems that do not naturally compose:

- Code repos explain implementation
- Service catalogs explain ownership
- Traces explain runtime behavior
- Confluence explains decisions and process
- Jira explains intent, status, and planned work
- OneDrive / SharePoint explain artifacts, specs, and business context

Humans bridge these systems manually. AI agents usually do not bridge them at all.

The result is the same structural failure everywhere: locally plausible work that is globally wrong. An engineer or agent can make a correct code change but miss the design doc, the rollout dependency, the ticket that changed the requirement, the incident that documented a known failure mode, or the downstream team that still depends on the old behavior.

This fragmentation creates four persistent costs:

1. **Unsafe changes.** Agents and engineers act on partial context.
2. **Slow decision-making.** People spend time reconstructing context instead of executing.
3. **Lost institutional memory.** Decisions exist, but not where work happens.
4. **Weak AI leverage.** Enterprises buy AI tools, but the tools lack the surrounding knowledge needed to operate safely.

The missing product is not another search box. It is a trustworthy context layer that turns scattered enterprise systems into grounded, queryable, machine-usable context.

---

## 3. Vision

SuperContext becomes the default context backbone for enterprise work. Within three years, asking an AI agent to change a system, investigate an incident, or answer a business-critical question without SuperContext should feel as incomplete as asking it to code without access to the repository.

---

## 4. Product thesis

The core product is a **unified enterprise context graph** with five properties:

- **Multi-source.** It spans code, runtime systems, docs, tickets, files, and ownership systems.
- **Provenance-first.** Every fact is grounded in where it came from.
- **Freshness-aware.** Every fact carries recency metadata.
- **Permission-aware.** Users and agents see only what they are allowed to see.
- **Machine-usable.** The graph is exposed through APIs and agent interfaces, not just dashboards.

The product is not “chat with your company data.” The product is a structured context layer that can power:

- natural-language questioning
- agent tool use
- workflow automation
- impact analysis
- planning and coordination

The user experience can look conversational. The underlying product must be graph-shaped.

---

## 5. Goals and non-goals

### Goals

- Give agents and humans a single context layer across engineering and operational knowledge
- Reduce mistakes caused by fragmented context
- Improve trustworthiness of AI-assisted work through citations, freshness, and explicit uncertainty
- Make enterprise knowledge machine-usable through APIs, MCP, and workflow hooks
- Start with a narrow wedge that reaches production value quickly, then expand along the same data model

### Non-goals

- We are not replacing source systems like GitHub, Jira, Confluence, OneDrive, or Datadog
- We are not trying to become a generic data lake or warehouse
- We are not training a foundation model
- We are not shipping every surface at once; the platform expands in phases

---

## 6. Product shape

SuperContext has one platform and multiple product slices on top of it.

### The platform

A context graph that models entities, relationships, provenance, freshness, and permissions across enterprise systems.

### Product slices

- **Product 1: Code and service context layer.** Focused on engineering system understanding and change safety.
- **Later slices:** docs and decisions, work tracking and intent, runbooks and incidents, file and artifact context, broader enterprise workflows.

The strategic idea is simple: one graph, multiple applications.

---

## 7. Product 1 in the platform

Product 1 is the first wedge because it has the clearest pain, strongest ground truth, and fastest trust loop.

It covers:

- repos and code structure
- APIs and schemas
- static call relationships
- runtime traces
- deployment topology
- ownership and service metadata

It does not initially cover:

- Confluence knowledge
- Jira planning and intent
- OneDrive / SharePoint files
- broad company search

Product 1 proves that SuperContext can deliver trustworthy, workflow-embedded answers in a domain where correctness matters and can be verified.

---

## 8. Core data model

The platform should be designed from day one around a generic graph model rather than a service-specific schema.

### Example entity types

- `Service`
- `Repo`
- `Endpoint`
- `Schema`
- `Event`
- `Deploy`
- `Database`
- `FeatureFlag`
- `Document`
- `Ticket`
- `Decision`
- `Runbook`
- `Incident`
- `File`
- `Person`
- `Team`

### Example relationship types

- `calls`
- `depends_on`
- `consumes`
- `produces`
- `owns`
- `documents`
- `mentions`
- `relates_to`
- `blocks`
- `planned_by`
- `resolved_by`
- `shares_with`

### Required metadata on facts

- source system
- source location
- last indexed at
- last observed at, where relevant
- confidence / derivation method
- access-control scope

This is the key engineering requirement that preserves the option to grow from Product 1 into the broader platform without a rewrite.

---

## 9. Surfaces

The platform should expose the same graph through multiple interfaces:

- **MCP / agent tools** for coding agents and enterprise assistants
- **Search / chat UI** for human exploration and question answering
- **Workflow hooks** for PRs, incidents, tickets, and reviews
- **CLI / REST API** for automation and internal integrations

Different product slices may emphasize different surfaces, but they should share the same underlying model and provenance rules.

---

## 10. Architecture principles

- **Ingest, do not replace.** Source systems remain the system of record.
- **Provenance on every fact.** No ungrounded assertions.
- **Small, composable tools.** Prefer structured APIs over giant prompt dumps.
- **Permission-preserving retrieval.** Access controls must survive indexing.
- **Incremental value.** Each new source should improve answers without requiring a full-platform rollout.

---

## 11. Roadmap

**Phase 1 — Product 1: code and service graph.**
Repos, contracts, runtime edges, deploy topology, MCP, PR bot, CLI.

**Phase 2 — engineering context expansion.**
Runbooks, incidents, schema registries, deployment gates, change-management signals.

**Phase 3 — enterprise knowledge expansion.**
Confluence, Jira, OneDrive / SharePoint, decisions, planning, and operational docs. Also: cross-tenant federation for cross-org service graphs (post-merger transitional period and permanently federated subsidiaries that own their own DevOps stacks).

**Phase 4 — cross-system agents and workflows.**
Planning, migration orchestration, impact memos, incident investigation, and enterprise copilots built on the shared graph.

---

## 12. Success metrics

### Leading indicators

- Time to first useful answer after source connection
- Number of grounded context lookups per active user or agent
- Citation click-through rate
- Coverage of core source systems within an account

### Lagging indicators

- Reduction in context-reconstruction time for common workflows
- Reduction in avoidable incidents and mis-coordinated changes
- Faster PR reviews, incident response, and onboarding
- Expansion from single-slice adoption into multi-slice adoption

### North-star metric

**High-stakes decisions or changes completed with grounded SuperContext support.**

This is broader than Product 1's incident metric and better matches the platform ambition.

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The product becomes vague “enterprise search” | Keep each product slice tied to a concrete workflow and measurable outcome |
| Trust erodes because answers are stale or weakly grounded | Require provenance, freshness, and explicit uncertainty everywhere |
| Permissions become a blocker | Preserve source-system ACLs and start with a narrow set of integrations that support them well |
| The platform tries to ingest everything too early | Sequence by high-trust wedges, starting with Product 1 |
| Product 1 architecture hardcodes service concepts | Use a generic entity-edge-metadata model from day one |

---

## 14. Open questions

1. Company-level name is `SuperContext`; GitHub repository rename is pending.
2. Should the long-term narrative lead with engineering context or broader enterprise context?
3. Which non-code system should be the first expansion after Product 1: Confluence, Jira, or OneDrive / SharePoint?
4. How much permission fidelity is required for the first enterprise expansion?
5. Which initial buyer is most likely to expand from Product 1 into the broader platform: platform engineering, CTO office, or enterprise architecture?
