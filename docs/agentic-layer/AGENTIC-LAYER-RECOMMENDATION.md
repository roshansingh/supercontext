# Agentic Layer Recommendation for Product 1

> **⚠️ SUPERSEDED — 2026-04-28.** This v0.1 conclusion (OpenAI Agents SDK) has been replaced by [`AGENTIC-LAYER-RECOMMENDATION-V2.md`](AGENTIC-LAYER-RECOMMENDATION-V2.md), which separates layers A/B/C and selects Claude Agent SDK for layers A+B with MCP-only on layer C. The reframing weighs built-in code-search primitives and self-hosted no-egress posture more heavily than the generic platform primitives evaluated here. See V2 §4 ("Why this V2 differs from v0.1") for the analytic difference. This document is preserved unchanged below for attribution and audit history; do not act on its conclusions.

---

**Status:** Draft v0.1 — superseded by V2
**Author:** Codex
**Date:** 2026-04-27

---

## Recommendation

For **Product 1**, we choose the **OpenAI Agents SDK** as the primary agentic layer.

We are **not** choosing LangGraph as the default starting point.

We are also **not** choosing the Claude Agent SDK for Product 1, even though it is a valid standalone orchestrator, because Product 1 is better served by a cleaner platform-oriented agent runtime than by a more opinionated workspace-centric harness.

---

## Why we chose it

Product 1 needs:

- MCP tool calling
- multi-step orchestration
- approvals / interruptions
- sessions / resumability
- tracing / observability
- a clean server-side integration story

The OpenAI Agents SDK has all of those as first-class documented features:

- **MCP support** for hosted MCP, Streamable HTTP, and stdio servers  
  Source: https://openai.github.io/openai-agents-js/guides/mcp
- **Tracing** built in by default for runs, tool calls, handoffs, and guardrails  
  Source: https://openai.github.io/openai-agents-js/guides/tracing
- **Sessions** with persistent memory and resumable runs  
  Source: https://openai.github.io/openai-agents-js/guides/sessions
- **Guardrails** for input, output, and tools  
  Source: https://openai.github.io/openai-agents-js/guides/guardrails
- **Handoffs** for multi-agent routing  
  Source: https://openai.github.io/openai-agents-js/guides/handoffs

That is a strong fit for a backend that must orchestrate graph queries, evidence retrieval, approvals, and PR-time workflows.

This choice is specifically driven by Product 1's shape:

- Product 1 is a **graph-backed engineering context platform**
- the agent layer sits **on top of** search, extraction, and graph queries
- the system needs strong **tool orchestration and observability**
- the system does **not** need a coding-agent-specific harness as its foundation

---

## Why not LangGraph first

LangGraph is powerful, but its own docs position it as a **low-level orchestration framework** focused on durable execution, stateful workflows, and human-in-the-loop control.

Sources:

- Overview: https://docs.langchain.com/oss/javascript/langgraph
- Durable execution: https://docs.langchain.com/oss/javascript/langgraph/durable-execution
- Persistence: https://docs.langchain.com/oss/javascript/langgraph/persistence

That is useful when you need:

- highly customized control flow
- long-running workflows
- explicit graph/state-machine orchestration
- deep persistence semantics

That is **not** the first problem Product 1 needs to solve.

For Product 1, LangGraph adds orchestration infrastructure before you have proven the core retrieval and graph product. It is more framework than you need at the start.

---

## Why not Claude Agent SDK as the default

The Claude Agent SDK is strongest when you want the harness behind **Claude Code** itself.

Its docs emphasize:

- built on the harness that powers Claude Code
- rich file operations and code execution
- project-local skills, hooks, slash commands, subagents, and plugins
- MCP extensibility
- advanced permissions

Sources:

- Overview: https://docs.claude.com/en/docs/agent-sdk/overview
- SDK overview: https://docs.claude.com/en/docs/claude-code/sdk/sdk-overview
- MCP: https://docs.claude.com/en/docs/claude-code/sdk/sdk-mcp
- Permissions: https://docs.claude.com/en/docs/agent-sdk/permissions

That is a very good fit for:

- coding agents
- local repo workflows
- “Claude Code inside my product”

But Product 1 is not mainly a local coding-agent harness. It is a **graph-backed context platform** with MCP, PR bot, CLI, and service-level reasoning. Claude Agent SDK is usable, but it is more tightly shaped around the Claude Code ecosystem than Product 1 needs.

---

## Short comparison

| Option | Best fit | Main downside for Product 1 |
|---|---|---|
| OpenAI Agents SDK | Production agent orchestration with built-in tracing, sessions, guardrails, MCP, approvals | Provider-specific, but less tied to a coding-product harness |
| Claude Agent SDK | Coding-agent experiences close to Claude Code | More coupled to Claude Code conventions and local agent harness patterns |
| LangGraph | Custom long-running workflows with deep state control | Too low-level and infrastructure-heavy for the first version |

---

## Final conclusion

We choose **OpenAI Agents SDK** for Product 1 because it gives us the right production primitives with the least unnecessary framework weight:

- **MCP support** for connecting Product 1 tools cleanly
- **sessions and resumability** for multi-step workflows
- **guardrails and approvals** for safe execution
- **handoffs** for multi-agent patterns if needed
- **built-in tracing** for debugging and production visibility

We are not choosing **LangGraph** because Product 1 does not yet need a low-level workflow framework with deeper custom state-machine orchestration.

We are not choosing **Claude Agent SDK** because, although it is a capable standalone orchestrator, Product 1 is not primarily a workspace-centric coding agent product. It is a graph-backed context platform, and OpenAI Agents SDK is the cleaner fit for that role.

If the product later shifts toward long-running custom workflow graphs, revisit **LangGraph**.

If the product later shifts toward a deeply workspace-native coding agent experience, revisit **Claude Agent SDK**.
