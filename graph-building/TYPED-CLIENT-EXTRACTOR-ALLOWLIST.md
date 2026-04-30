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

