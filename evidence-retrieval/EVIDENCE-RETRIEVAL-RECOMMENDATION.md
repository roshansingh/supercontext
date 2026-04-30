# Evidence Retrieval Recommendation — Product 1

- **Status:** Accepted
- **Date:** 2026-04-29
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** `claude-evidence-retrieval-research.md`, `codex-evidence-retrieval-research.md`, and `codex-runtime-retrieval-patterns.md` as decision inputs
- **Binding ADR:** [`../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`](../adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md)

---

## Final recommendation

**Build a modular evidence-retrieval layer owned by SuperContext.**

The final architecture:

- **Mode A:** commit-pinned coordinate fetch for surfaced and safety-critical claims
- **Mode B:** selective retrieval ladder: `ripgrep` -> `ast-grep` / `tree-sitter` -> budgeted Claude Agent SDK Explorer
- **Runtime model:** graph retrieval and evidence retrieval are both first-class; graph gives structure, evidence gives grounding

## OSS posture

Use OSS primitives:

- `go-git` / `pygit2`
- `ripgrep`
- `tree-sitter`
- `ast-grep`
- Claude Agent SDK built-ins

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
- `Zoekt` should be supported later as the scalable indexed lexical backend when measured scale requires it.
- `Sourcebot` is reference-only, not the runtime dependency.
- `Semble` is optional / experimental for fuzzy code search, not the evidence backbone.
- Code-chunk embeddings are not the primary evidence path.

## Historical inputs

- [`claude-evidence-retrieval-research.md`](./claude-evidence-retrieval-research.md)
- [`codex-evidence-retrieval-research.md`](./codex-evidence-retrieval-research.md)
- [`codex-runtime-retrieval-patterns.md`](./codex-runtime-retrieval-patterns.md)
- [`../debates/1-2026-04-29-finalize-evidence-retrieval-architecture.md`](../debates/1-2026-04-29-finalize-evidence-retrieval-architecture.md)

Read those as research and debate history, not as open decisions.

