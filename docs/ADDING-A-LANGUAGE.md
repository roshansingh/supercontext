# Adding Language Support

This repo treats language support as a source plugin. A new language should reuse the existing KG ontology unless it introduces a product concept that cannot fit the current nodes and relations.

Start by copying `source/kg/languages/_template/` into `source/kg/languages/<language>/`.

## Required Files

- `files.py`: lightweight file matcher used during repo discovery. Do not import extractors or heavy optional dependencies here.
- `language.py`: exports `LANGUAGE_SUPPORT` and wires adapters, known stacks, dimension rules, package resolvers, and opportunity detectors.
- `known_stacks.yaml`: source-of-truth mapping from import roots/package names to categories.
- `dimension_rules.yaml`: maps language files into product dimensions such as `backend`, `frontend`, `infra`, or `data`.
- `extractors/`: parser bridge, extractor, and adapter code when the language emits KG facts.

Register both pieces:

- Add `LANGUAGE_FILES` to `source/kg/languages/file_matchers.py` or the registered matcher list used by repo discovery.
- Add `LANGUAGE_SUPPORT` to `source/kg/languages/__init__.py`.
- Add YAML/package assets to `[tool.setuptools.package-data]` in `pyproject.toml`.
- Add optional parser/runtime dependencies under a named extra if they are not needed for default installs.

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

Run at least:

```bash
python -m compileall -q source
python -m unittest discover -s tests
```

For parser-backed languages, also run the focused language tests and adapter fixture tests. If parser dependencies are optional, ensure tests either install the extra in CI or skip clearly when the extra is missing.
