# ADR-0008: Use Deterministic Import Normalization with Agentic Candidate Fallback

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

The first KG implementation slice extracts raw Python import facts from a representative Python repository.

Smoke testing showed the raw import facts are useful but too literal:

- `import pandas as pd` becomes `pandas`
- `from sklearn.model_selection import train_test_split` becomes `sklearn.model_selection`
- `from mercury_ml.chatbot.apis.openai_instructor import X` becomes `mercury_ml.chatbot.apis.openai_instructor`
- standard-library imports such as `os`, `json`, `logging`, and `pickle` dominate aggregate dependency output
- internal modules and third-party packages are not clearly separated

Raw imports are syntax facts. Product queries need normalized dependency facts:

- which modules depend on OpenAI?
- which code paths use sklearn?
- which modules depend on this internal module?
- which third-party packages are central?
- which dependencies are standard library noise and should be deprioritized?

Import normalization is the layer that turns raw language import syntax into classified dependency facts with evidence.

## Decision

**Use deterministic import normalization as the v1 path. Agent SDK may only produce candidate classifications for ambiguous or missing cases, and only in a later v2 if measured evidence shows it helps.**

The deterministic normalizer must:

1. Parse imports from language syntax, not free text.
2. Read project metadata such as `pyproject.toml`, lockfiles, package manifests, and repo layout.
3. Resolve relative imports using the current module path.
4. Classify imports into normalized categories.
5. Emit normalized dependency facts with source coordinates.
6. Preserve the raw import as evidence/debug metadata.

## Normalized Import Categories

| Category | Meaning | Example |
|---|---|---|
| `stdlib` | Runtime/language standard library dependency. Usually low product-impact signal. | `import os`, `import json`, `import logging` |
| `third_party` | External package dependency from package metadata or known import/distribution mapping. | `import pandas`, `from sklearn.model_selection import train_test_split` |
| `internal_module` | Import targets a module inside the current repo/package. | `from mercury_ml.chatbot.apis.openai_instructor import X` |
| `relative_internal_module` | Relative import resolved to an internal module path. | `from .utils import clean_text` |
| `unknown` | Import cannot be classified deterministically. | dynamic or missing metadata case |

## Examples

| Raw import | Normalized target | Category | Comment |
|---|---|---|---|
| `import pandas as pd` | `pandas` | `third_party` | Alias is ignored for dependency identity. |
| `from sklearn.model_selection import train_test_split` | `sklearn` / distribution `scikit-learn` | `third_party` | Import root and distribution name may differ; preserve both when known. |
| `from mercury_ml.chatbot.apis.openai_instructor import instructor` | `mercury_ml.chatbot.apis.openai_instructor` | `internal_module` | Should point to an internal `CodeModule` when indexed. |
| `from .utils import clean_text` | resolved module path from current package | `relative_internal_module` | Requires current module context. |
| `import os` | `os` | `stdlib` | Keep as evidence, but deprioritize in dependency views. |

## Deterministic V1 Algorithm

For Python v1:

1. Parse `ast.Import` and `ast.ImportFrom` nodes.
2. Capture raw import text, module path, imported names, aliases, and line coordinates.
3. Build project metadata from:
   - `pyproject.toml`
   - lockfile when available
   - package include roots such as `packages = [{include = "mercury_ml"}]`
   - repository module tree
4. Build classification maps:
   - standard library module set for the target Python version
   - project package roots, for example `mercury_ml`
   - declared dependency names, for example `openai`, `pandas`, `requests`
   - known distribution/import aliases, for example `scikit-learn` → `sklearn`
5. Classify each import:
   - relative import → resolve against current module, classify as `relative_internal_module` if target exists
   - starts with project package root → `internal_module`
   - root in stdlib set → `stdlib`
   - root or known alias in dependency map → `third_party`
   - otherwise → `unknown`
6. Emit normalized facts with `deterministic_static` evidence and source coordinates.

## Fact Shape

The exact table/schema shape remains owned by the Tool Query Contract and graph-building implementation, but v1 facts must include these semantics:

```json
{
  "predicate": "IMPORTS",
  "subject": "module_id",
  "object": "dependency_id",
  "qualifier": {
    "raw_import": "from sklearn.model_selection import train_test_split",
    "import_root": "sklearn",
    "distribution_name": "scikit-learn",
    "category": "third_party",
    "imported_names": ["train_test_split"],
    "alias": null
  },
  "evidence": {
    "derivation_class": "deterministic_static",
    "repo": "mercury_ml",
    "commit_sha": "c83cacf...",
    "path": "mercury_ml/chatbot/frustration_classification/train.py",
    "line_start": 2,
    "line_end": 2
  }
}
```

## Query Behavior

Normalized imports should support:

- `modules_importing(package="openai", category="third_party")`
- `modules_importing(package="sklearn", include_distribution_aliases=true)`
- `modules_importing(module="mercury_ml.chatbot.apis.openai_instructor", category="internal_module")`
- `top_dependencies(exclude_stdlib=true)`
- `who_imports_internal_module(module_id)`
- `dependency_blast_radius(package_or_module)`

Standard-library imports remain stored because they are evidence, but product views should usually exclude or down-rank them unless the user explicitly asks for them.

## Agent SDK Candidate Fallback

Agent SDK is not part of the v1 primary path.

Allowed future candidate cases:

- missing or inconsistent dependency metadata
- monorepos where package boundaries are not declared
- ambiguous import roots that map to multiple distributions
- dynamic imports such as `importlib.import_module(...)`
- framework/plugin imports where the dependency is configured outside Python syntax
- import side effects that need explanation, not just classification

Agent SDK fallback requirements:

- run only after deterministic normalization returns `unknown` or ambiguous output
- use read-only tools and explicit budgets per ADR-0001 and ADR-0005
- return candidate classifications with file/line evidence
- mark output as candidate / inferred until deterministic metadata confirms it
- never override a deterministic classification without explicit evidence

## V2 Agentic Expansion Criteria

A later v2 may use Agent SDK more actively only if measured evidence shows it improves the import-normalization layer.

Evidence required:

- measurable reduction in `unknown` classifications on real repos
- no measurable increase in false internal/third-party classifications
- p95 latency and token cost within query budget
- every agent-proposed classification cites concrete files/lines or manifest entries
- deterministic promotion path exists before agent-proposed classifications affect safety-critical answers

Until then, the binding v1 posture is deterministic normalization first, Agent SDK candidate fallback later.

## V1 Scope

Initial scope:

- Python import normalization for the local KG harness
- `pyproject.toml` dependency and package-root parsing
- standard-library classification
- internal vs third-party vs relative vs unknown classification
- distribution/import alias map for common cases needed by the input repo, starting with `scikit-learn` → `sklearn`
- compact query output that can exclude or down-rank standard-library imports

Explicitly out of v1:

- broad package-manager support across all languages
- dynamic import resolution as canonical fact
- dependency vulnerability / license analysis
- transitive dependency graph from lockfiles
- agent-first import classification
- promoting Agent SDK classifications without deterministic corroboration

## Implementation Status (v0, 2026-05-08)

This ADR is partially implemented in the local KG harness.

What exists now:

- Python deterministic import normalization in `source/kg/normalization/python/imports.py`.
- TypeScript/JavaScript deterministic import normalization in `source/kg/normalization/typescript/imports.py`.
- Python categories: `stdlib`, `third_party`, `internal_module`, `relative_internal_module`, `unknown`.
- TypeScript/JavaScript categories: `node_builtin`, `third_party`, `internal_module`, `relative_internal_module`, `unknown`.
- Metadata parsing from `pyproject.toml` and `package.json`.
- Common Python distribution/import alias handling, including `sklearn` to `scikit-learn`.
- Query surfaces over normalized imports:
  - `modules-importing`
  - `dependency-info`
  - `top-dependencies`
  - `who-imports`
  - `top-internal-dependencies`
  - `modules-importing-both`

What is still pending:

- Agent SDK candidate fallback.
- Broad package-manager and lockfile support.
- Dynamic import resolution.
- Cross-repo package-to-repo linking.
- Vulnerability/license/transitive dependency analysis.

Evaluation evidence:

- `docs/evaluation/LOW-QUERY-RERUN-IMPORT-NORMALIZATION-2026-05-06.md`
- `docs/evaluation/LOW-QUERY-RERUN-TRUE-LOOP-PARSER-BACKED-2026-05-08.md`
- `docs/evaluation/MEDIUM-QUERY-AGGREGATION-RUN-2026-05-08.md`

## Relationship to Existing ADRs

### ADR-0005

Import normalization produces source-code-backed facts. Any surfaced claim must still be groundable by ADR-0005 Mode A coordinate fetch.

Unknown or ambiguous imports may trigger ADR-0005 Mode B search later, but Mode B is not the primary normalizer.

### ADR-0006

ADR-0006 keeps Product 1 focused on service, API, event, deploy, owner, and evidence facts. This ADR does not add package dependencies as Product 1 canonical ontology nodes.

Normalized imports are implementation/query-support facts for the KG module. They can support source-level evidence, symbol lookup, dependency views, and future graph-building, but canonical product answers must still respect the accepted ontology and tool contracts.

### ADR-0007

Import normalization complements deterministic symbol lookup:

- symbol lookup resolves code entities
- import normalization resolves dependency targets
- both use deterministic v1 resolution with Agent SDK only as bounded candidate fallback

## Consequences

### Positive

- Removes noise from dependency queries by separating stdlib, third-party, internal, and unknown imports.
- Makes `openai`, `sklearn`, `pandas`, and internal module dependencies queryable without substring hacks.
- Improves impact queries such as "who imports this internal module?"
- Keeps import facts deterministic, cheap, and testable.

### Negative

- Requires per-language import normalizers.
- Requires maintaining small alias maps where import root differs from distribution name.
- Monorepos and dynamic imports will still need later fallback handling.

### Neutral

- This ADR does not require Postgres / AGE before it is useful.
- This ADR does not define the full Tool Query Contract schema.
- This ADR does not make package/dependency nodes part of the Product 1 canonical ontology.

## References

- `source/KG-QUERY-SMOKE-TESTS.md`
- `source/kg/extraction/python/ast_extractor.py`
- `source/kg/normalization/python/imports.py`
- `source/kg/extraction/typescript/compiler_api_extractor.py`
- `source/kg/normalization/typescript/imports.py`
- ADR-0001: `adr/0001-claude-agent-sdk-for-internal-runtime.md`
- ADR-0005: `adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`
- ADR-0006: `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- ADR-0007: `adr/0007-deterministic-symbol-lookup-with-agentic-disambiguation.md`
