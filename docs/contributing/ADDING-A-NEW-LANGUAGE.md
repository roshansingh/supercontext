# Adding a New Language

This repo treats language support as a source plugin. A new language should reuse
the existing KG ontology unless it introduces a product concept that cannot fit
the current nodes and relations.

The language plug-in boundary is intentionally split in two:

- `files.py` is lightweight file discovery. It must not import extractors, adapters, or `RepoSnapshot`.
- `language.py` is full extraction support. It can import parser code, adapters, known-stack mappings, and package-resolution helpers.

This split keeps repo discovery import-safe while still making each language own its extraction behavior.

## Required Files

- `files.py`: lightweight file matcher used during repo discovery.
- `language.py`: exports `LANGUAGE_SUPPORT` and wires adapters, known stacks, dimension rules, package resolvers, and opportunity detectors.
- `known_stacks.yaml`: source-of-truth mapping from import roots/package names to categories.
- `dimension_rules.yaml`: maps language files into product dimensions such as `backend`, `frontend`, `infra`, or `data`.
- `extractors/`: parser bridge, extractor, and adapter code when the language emits KG facts.

## Steps

1. Copy `source/kg/languages/_template/` to `source/kg/languages/<language_name>/`, including `__init__.py`.
2. Update `files.py`:
   - `name`: canonical language key, such as `java`.
   - `aliases`: emitted labels or ecosystem aliases, such as `("javascript",)` for TypeScript.
   - `file_extensions`: source extensions used to prefilter candidate files.
   - `manifest_files`: package/build manifests used to prefilter candidate files.
   - `matches_file(path)`: exact source-file predicate for those candidates. Put exclusions here, such as TypeScript `.d.ts` files.
3. Update `language.py`:
   - `source_roots(repo, ctx)` for known-stack coverage labels.
   - `adapters()` for language-owned adapters.
   - `known_stacks()` for unsupported known framework coverage.
   - Keep parser-specific code behind adapters or helper modules until the build path needs a shared parser hook.
4. Add YAML/package assets to `[tool.setuptools.package-data]` in `pyproject.toml`.
5. Add optional parser/runtime dependencies under a named extra if they are not needed for default installs.
6. Add tests under `tests/languages/`.

Do not add a central adapter registry edit for a language-owned adapter unless it is still part of the legacy compatibility path. New languages should be discovered from their directory.

## Extractor Rules

Emit existing concepts first: `Repo`, `Service`, `CodeModule`, `CodeSymbol`, `Endpoint`, `Schema`, `EventChannel`, `Deployable`, `Deployment`, and `Environment`.

Prefer parser-backed extraction over regex or keyword matching. If the parser cannot prove a fact, fail closed: emit no fact or emit coverage explaining the gap. Do not create junk facts to make coverage look better.

Keep these boundaries clear:

- Ontology: product concepts and relations.
- Language support: file matching, source roots, package manifests, dimension rules, known stacks.
- Extractors: language/framework-specific parsing and fact construction.
- Metrics: consume emitted evidence and coverage; do not depend on language-specific hacks.

## Parser Checklist

Before opening a PR, check language semantics that can silently corrupt KG identity:

- Namespace/package/module qualification is included in `CodeSymbol` identities.
- Overloads, constructors, generated methods, or equivalent duplicate names have stable disambiguators.
- Aliased imports record the target package/namespace, not only the local alias.
- Ambiguous call or import resolution fails closed.
- Build/generated output is ignored, for example `.NET` `bin/` and `obj/` directories.
- Optional dependency errors include actionable install guidance.
- Cached YAML/config returns deep copies or immutable data.

## Tests To Add

Add focused tests for:

- File matching and generated-output exclusions.
- Language wrapper contract: adapters, known stacks, dimension rules, package resolver, useful edges.
- Parser bridge output for imports, symbols, calls, aliases, namespaces, and overloads.
- Extractor output for entities, facts, evidence, coverage, and bytes refs.
- Known-stack coverage fixtures under `tests/framework/known_stacks/<language>/`.
- Adapter fixtures under `tests/adapters/<adapter-name>/`.
- Packaging metadata for YAML/assets in `pyproject.toml`.
- YAML shape validation for `known_stacks.yaml` and `dimension_rules.yaml`.

## Verification

Run focused checks:

```bash
python3 -m unittest discover -s tests/languages
python3 -m unittest tests.test_adapter_framework tests.test_multi_repo_identity
python3 -m source.scripts.run_product_validation
```

Run `python3 -m unittest discover -s tests` as a wider regression check when the repository baseline is green. If the baseline has unrelated known failures, record those separately instead of treating them as new-language failures.

For parser-backed languages, also run the focused language tests and adapter fixture tests. If parser dependencies are optional, ensure tests either install the extra in CI or skip clearly when the extra is missing.
