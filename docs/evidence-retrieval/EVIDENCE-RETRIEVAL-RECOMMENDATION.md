# Evidence Retrieval Recommendation — Product 1

- **Status:** Accepted
- **Date:** 2026-04-29
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** prior paired evidence-retrieval research notes and runtime retrieval pattern notes as decision inputs
- **Binding ADR:** [`../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`](../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md)

---

## Final recommendation

**Build a modular evidence-retrieval layer owned by SuperContext.**

The final architecture:

- **Mode A:** commit-pinned coordinate fetch for surfaced and safety-critical claims
- **Mode B:** selective retrieval ladder: `ripgrep` -> targeted `ast-grep` / `tree-sitter` only when required -> budgeted Claude Agent SDK Explorer
- **Runtime model:** graph retrieval and evidence retrieval are both first-class; graph gives structure, evidence gives grounding

## OSS posture

V1 binding choices:

- `go-git` / `pygit2`
- `ripgrep`
- Claude Agent SDK built-ins

Targeted v1 only:

- `tree-sitter`
- `ast-grep`

These are used only for specific framework or syntax patterns required by the first design partner, not as broad language coverage.

Build ourselves:

- orchestration
- adapter interfaces
- provenance contract
- refusal semantics
- graph/evidence merge logic
- budget gates

## Platform posture

This is an open-source enterprise platform decision, not a fixed v1 script.

- `ripgrep` is the default lexical backend.
- `Zoekt` is a planned scale extension after benchmarks show `ripgrep` is insufficient at target repo scale.
- `Sourcebot` is reference-only, not the runtime dependency.
- `Semble` is future research only, not a v1 component or evidence backbone.
- Code-chunk embeddings are not the primary evidence path.

## Historical inputs

The paired research notes and the runtime retrieval patterns note were consolidated into this recommendation. Read this document and the linked debate as the surviving decision history:

- [`../debates/1-2026-04-29-finalize-evidence-retrieval-architecture.md`](../debates/1-2026-04-29-finalize-evidence-retrieval-architecture.md)
