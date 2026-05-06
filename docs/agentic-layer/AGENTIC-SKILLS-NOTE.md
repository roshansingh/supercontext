# Agentic Skills Note

> **✅ RESOLVED — 2026-04-28.** The deferred decision in this note ("Is skills-based progressive disclosure important enough to optimize for as a first-class runtime feature?") is now resolved in [`AGENTIC-LAYER-RECOMMENDATION-V2.md`](AGENTIC-LAYER-RECOMMENDATION-V2.md) §5. **Answer: yes**, skills are central enough to matter and Claude Agent SDK wins on this axis today. This document is preserved unchanged below for context; the binding decision lives in V2.

---

**Status:** Draft — open question now resolved in V2
**Date:** 2026-04-27

---

## Why this note exists

We are **not finalizing** the agentic layer decision yet.

The open concern is that **skills** are a very strong abstraction because they let us keep the base prompt small and load workflow-specific instruction bundles only when needed.

That matters for Product 1 because coordinator prompts can otherwise bloat with:

- routing rules
- output contracts
- tool-specific formatting rules
- workflow-specific policies

---

## What we observed

### Claude Agent SDK

Claude-style skills are already a strong, native pattern.

What that gives:

- skill directories with `SKILL.md`
- compact upfront metadata
- full instructions loaded only when relevant
- a clear progressive-disclosure model for conditional recipes

This matches the use case we care about very closely.

Sources:

- https://docs.claude.com/en/docs/agent-sdk/overview
- https://docs.claude.com/en/docs/agent-sdk/skills
- https://code.claude.com/docs/en/skills

### OpenAI Agents SDK

OpenAI clearly invests in skills, but today the strongest support is around **shell/sandbox environments**, not plain coordinator agents.

What we found:

- OpenAI has an official **Skills** guide
- skills use `SKILL.md`
- skills are supported in **hosted shell** and **local shell**
- the model can see skill metadata first and decide when to use a skill
- the Python SDK has a documented `Skills` capability for `SandboxAgent`

Sources:

- https://developers.openai.com/api/docs/guides/tools-skills
- https://developers.openai.com/api/docs/guides/tools-shell
- https://openai.github.io/openai-agents-python/ref/sandbox/capabilities/skills/
- https://github.com/openai/skills

Important nuance:

- In the main Agents SDK docs, skills are **not** presented as a core plain-agent primitive alongside agents, tools, handoffs, guardrails, sessions, and tracing.
- The current official shape is stronger for **shell/sandbox skill usage** than for **general lazy instruction modules for coordinator agents**.

Sources:

- https://openai.github.io/openai-agents-js/
- https://openai.github.io/openai-agents-python/

### Specific signal to watch

There is an explicit request for **lazy-loaded instruction skills for normal Agents SDK orchestration** in OpenAI's Python repo.

That request describes exactly the pattern we care about:

- compact skill registry
- load full instructions only when needed
- avoid bloating the coordinator prompt

But as of **April 27, 2026**, it is only an issue, not an announced product direction.

Source:

- https://github.com/openai/openai-agents-python/issues/2906

---

## Current conclusion

We should treat this as an **open architectural question**.

Current read:

- **Claude Agent SDK** has the stronger native story for instruction skills today
- **OpenAI Agents SDK** has meaningful skills support, but it is currently more tied to shell/sandbox workflows
- OpenAI may move toward first-class instruction skills for plain agents, but we do **not** yet have strong enough evidence to assume that

---

## Decision status

Decision is intentionally deferred.

When we revisit, the key question should be:

**Is the Product 1 agent layer primarily a graph-backed platform orchestrator, or is skills-based progressive disclosure important enough that we should optimize for it as a first-class runtime feature?**

If skills turn out to be central, that may change the SDK choice.
