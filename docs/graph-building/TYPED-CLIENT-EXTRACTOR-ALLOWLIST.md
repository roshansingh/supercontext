# Typed Client Extractor Allowlist

- **Status:** Stub for ADR-0006 implementation follow-up
- **Owner:** Graph-building / ingestion module
- **Purpose:** Define which deterministic static call-site extractors are trusted enough to auto-promote `CALLS` facts in Product 1 v1.

---

## Decision Boundary

ADR-0006 allows `CALLS` promotion from an allowlisted high-precision `deterministic_static` typed-client call-site extractor.

This file is the registry for that allowlist. It exists so the ontology ADR does not hardcode every language/framework rule inline.

## V1 Rule

An extractor may be allowlisted only when it:

- targets a specific typed client framework or generated client shape
- emits source coordinates compatible with ADR-0005 Mode A
- has contract tests proving low false-positive behavior on representative fixtures
- records extractor name and version in evidence rows
- does not rely on broad language-indexer coverage or probabilistic inference

Each allowlisted extractor requires a dedicated ruleset, correctness fixtures, and ongoing maintenance per language/framework. Broad upfront coverage is non-trivial; the allowlist expands by design-partner demand, not on a fixed roadmap. When ingestion encounters code in a language/framework with no allowlisted extractor, it must emit an `uninstrumented` coverage row for the extractor's declared scope, such as repo, service, language/framework, or path prefix (see `BACKLOG.md` "Loud refusal at ingestion") rather than silently skip — preserving the refusal-on-uninstrumented contract from PRD §7.

## Initial Entries

No extractor is allowlisted yet.

The first implementation pass should add entries based on the first design partner's stack.

Expected candidate families from `PRD.md` are:

- TypeScript / JavaScript typed HTTP clients
- Go typed HTTP or gRPC clients
- Java / Kotlin typed HTTP or gRPC clients

Each added entry must include:

- language
- framework / generated-client pattern
- extractor name
- extractor version
- evidence coordinates emitted
- test fixture path
- promotion rationale

## Prototype JS/TS Client Coverage Reasons

The local prototype parser-backed JS/TS client extractor emits unresolved `CALLS_ENDPOINT` coverage reasons before this extractor is promoted into the Product 1 allowlist. Current dynamic-template reasons:

| Reason | Meaning |
|---|---|
| `template_dynamic_expression_unsafe` | Template target contains a dynamic span that is not a bare identifier, property access, or string-key element access. |
| `template_dynamic_composite_segment` | Template target has dynamic content mixed with other content inside one path segment, such as `${a}-${b}` or adjacent spans. |
| `template_dynamic_host_position` | Template target has dynamic content in host/base position, so the extractor cannot prove a local endpoint path. |
