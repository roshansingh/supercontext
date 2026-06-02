# Adding a New Language

This repo treats language support as a source plugin. A new language should
reuse the existing KG ontology and adapter framework first. Add ontology only
when a product concept cannot be represented by the current entity kinds,
canonical predicates, or support predicates.

The language plugin boundary is intentionally split in two:

- `files.py` is lightweight file discovery. It must not import extractors,
  adapters, parser dependencies, or `RepoSnapshot`.
- `language.py` is full extraction support. It can import parser code,
  adapters, known-stack mappings, dimension rules, package-resolution helpers,
  consumer-manifest extractors, and useful-edge metadata.

This split keeps repo discovery import-safe while still making each language
own its extraction behavior.

## Required Files

- `files.py`: lightweight file matcher used during repo discovery.
- `language.py`: exports `LANGUAGE_SUPPORT` and implements the language support
  contract from `source/kg/languages/types.py`.
- `known_stacks.yaml`: source-of-truth mapping from import roots/package names
  to categories for unsupported known-stack coverage.
- `dimension_rules.yaml`: maps language files into product dimensions such as
  `backend`, `frontend`, `infra`, or `data`.
- `extractors/`: parser bridge, extractor, and adapter code when the language
  emits KG facts.
- Optional language assets such as consumer-manifest rules or useful-edge
  metadata when the language needs them.

Use `source/kg/languages/_template/` as the starting point. The current
`language.py` hook surface is:

- `source_roots(repo, ctx)`
- `parse_repo(repo, ctx)`
- `opportunity_detectors()`
- `package_resolver()`
- `consumer_manifest_extractor()`
- `dimension_rules()`
- `useful_edges()`
- `adapters()`
- `known_stacks()`

## Coverage And Metrics Contract

Coverage metrics are language-neutral. They must keep consuming canonical
snapshot rows rather than adding language-specific branches in metric formulas.
A language makes those metrics meaningful by emitting the shared inputs the
metrics already understand.

For a first-class language, wire these pieces deliberately:

- `files.py` identifies real source files and excludes generated output. This
  feeds `manifest.counts.files_by_language` and the
  `M_dimension_classification` denominator.
- `dimension_rules.yaml` maps source files into product dimensions using
  imports, packages, manifest files, or file extensions. Package rules are fed
  by the language's `consumer_manifest_extractor()`, not by metric-specific
  parsing code.
- `known_stacks.yaml` plus `source_roots(repo, ctx)` tells the build which
  recognized frameworks/transports should produce explicit coverage rows when
  support is partial or missing.
- `adapters()` should emit canonical facts with valid evidence coordinates.
  Unsupported, ambiguous, or dynamic shapes should emit `Coverage` rows with a
  precise `state`, `predicate`, `scope_ref`, and reason instead of returning
  empty results silently.
- `package_resolver()` and `consumer_manifest_extractor()` should be added
  together for package ecosystems. This keeps cross-repo linkage and
  package-based dimension classification aligned.
- `opportunity_detectors()` should be added for high-value predicates where we
  want `M_extractor_opportunity` and `M_silent_gap` to measure missed value. If
  no detector exists, those metrics should be interpreted as `n_a`, not as a
  sign that coverage is complete.
- `useful_edges()` can stay empty until the language has language-owned useful
  edge metadata. Product-dimension useful edges remain in
  `source/kg/metrics/useful_edges.yaml`.

When improving coverage for an existing language, improve the language-owned
extractor, manifest, resolver, known-stack, or opportunity detector first.
Only change metric formulas when the canonical metric contract itself is
wrong for every language.

## Steps

1. Copy `source/kg/languages/_template/` to
   `source/kg/languages/<language_name>/`, including `__init__.py`.
2. Update `files.py`:
   - `name`: canonical language key, such as `java`.
   - `aliases`: emitted labels or ecosystem aliases, such as `("javascript",)`
     for TypeScript.
   - `file_extensions`: source extensions used to prefilter candidate files.
   - `manifest_files`: package/build manifests used to prefilter candidate
     files.
   - `matches_file(path)`: exact source-file predicate for those candidates.
     Put generated-output exclusions here, such as TypeScript `.d.ts` files or
     .NET `bin/` and `obj/` directories.
3. Update `language.py`:
   - `source_roots(repo, ctx)` for known-stack coverage labels.
   - `parse_repo(repo, ctx)` if several adapters should share one parser pass.
   - `package_resolver()` for dependency/provider identity.
   - `consumer_manifest_extractor()` for manifest dependencies used by relink.
   - `dimension_rules()` and `useful_edges()` for metrics.
   - `adapters()` for language-owned adapters.
   - `known_stacks()` for unsupported known framework coverage.
4. Add YAML/package assets to `[tool.setuptools.package-data]` in
   `pyproject.toml`.
5. Add optional parser/runtime dependencies under a named extra if they are not
   needed for default installs.
6. Add focused tests under `tests/languages/`, `tests/adapters/`, or a
   language-specific test file.
7. Add or update coverage metric tests when the language changes dimension
   assignment, opportunity detection, package manifests, or explicit coverage
   rows.

Do not add a central adapter registry edit for a language-owned adapter unless
it is still part of the legacy compatibility path. New languages should be
discovered from their directory.

If the extractor is for a language-agnostic file format, put it under
`source/kg/file_formats/adapters/` instead of a language directory. Examples
include Kubernetes YAML, OpenAPI, Terraform, Serverless, Zappa, dotenv, Apache
vhost, and other config formats.

## Adapter Contract

Language extractors should expose adapter objects with an `AdapterCapability`
and return an `AdapterResult`.

Every adapter capability must declare:

- `name`
- `languages`
- `source_system`
- `produces_entity_kinds`
- `produces_predicates` for canonical KG facts
- `produces_support_predicates` when emitting implementation support facts
- `ontology_scope`: `canonical`, `implementation_support`, or `mixed`

The runner validates emitted rows against
`source/kg/extraction/framework/allowlists.py`. Today, supported entity kinds
include `Service`, `Repo`, `CodeModule`, `CodeSymbol`, `ExternalPackage`,
`ExternalSymbol`, `Endpoint`, `Domain`, `EnvVar`, `DeployTarget`, and
`EventChannel`.

Use canonical facts for durable cross-repo product concepts such as calls,
imports, endpoint exposure, endpoint consumers, domains, deploy targets, env
vars, and event channels. Use support facts for framework/application details
that help answer product questions but are not part of the canonical ontology,
such as model fields, model relationships, serializers, handlers, and tasks.
Support facts are written to `support_facts.jsonl`; they are not silently mixed
into `facts.jsonl`.

If a new predicate or entity kind is genuinely needed, update the allowlist,
construction path, serialization path, query/packet consumer, and tests in the
same change. Do not add one-off strings in extractor code.

## Extractor Rules

Prefer parser-backed extraction over regex or keyword matching. If the parser
cannot prove a fact, fail closed: emit no fact or emit coverage explaining the
gap. Do not create junk facts to make coverage look better.

Keep these boundaries clear:

- Ontology: product concepts and relations.
- Language support: file matching, source roots, package manifests, dimension
  rules, useful edges, known stacks, and consumer manifests.
- Extractors: language/framework-specific parsing and fact construction.
- File-format adapters: language-agnostic config parsing.
- Metrics: consume emitted evidence and coverage; do not depend on
  language-specific hacks.

Use the shared `ExtractionContext` caches when work can be reused across
adapters in one build:

- `ctx.parsed_by_language` for parser output.
- `ctx.literal_indexes_by_language` for literal/reference indexes.
- `ctx.import_roots_by_language` for known-stack coverage.
- `ctx.config_scans` for shared config-file scans.

Avoid reparsing the same files in each adapter. When one AST helper is split
into parallel collectors, keep nested-scope and source-order semantics aligned
or centralize the traversal policy.

## Parser Checklist

Before opening a PR, check language semantics that can silently corrupt KG
identity:

- Namespace/package/module qualification is included in `CodeSymbol`
  identities.
- Overloads, constructors, generated methods, or equivalent duplicate names
  have stable disambiguators.
- Aliased imports record the target package/namespace, not only the local alias.
- Local bindings and source order are respected. If a name is locally bound but
  not statically resolvable, do not fall through to a same-named global.
- Ambiguous call, receiver, import, or package resolution fails closed.
- Build/generated output is ignored.
- Optional dependency errors include actionable install guidance.
- Cached YAML/config returns deep copies or immutable data.
- Evidence rows include `bytes_ref` unless the source system is explicitly
  allowed to omit it.

## Tests To Add

Add focused tests for:

- File matching and generated-output exclusions.
- Language wrapper contract: adapters, known stacks, dimension rules, package
  resolver, consumer manifest extractor, and useful edges.
- Parser bridge output for imports, symbols, calls, aliases, namespaces,
  overloads, receiver binding, and constructor calls where relevant.
- Extractor output for entities, canonical facts, support facts, evidence,
  coverage, and bytes refs.
- Support fact persistence when the language emits support facts.
- Known-stack coverage fixtures under `tests/framework/known_stacks/<language>/`.
- Adapter fixtures under `tests/adapters/<adapter-name>/`.
- Packaging metadata for YAML/assets in `pyproject.toml`.
- YAML shape validation for `known_stacks.yaml`, `dimension_rules.yaml`, and
  useful-edge metadata.
- Coverage metric contract tests proving dimension classification, opportunity
  coverage, silent-gap behavior, or `n_a` states are honest for the language.
- Consumer-manifest tests proving package dependencies feed package-based
  dimension rules without adding language-specific parsing to metrics.

Useful existing tests to mirror or extend:

```bash
python -m unittest discover -s tests/languages
python -m unittest tests.framework.test_adapter_contract tests.test_adapter_framework
python -m unittest tests.test_packaging_metadata tests.metrics.test_yaml_shapes tests.metrics.test_dimension_classifier
```

For behavior changes, add an extractor-specific regression test for the exact
shape being supported and a negative fixture proving the rule is not tuned to
one repo or one goldset question.

## Verification

Run focused checks:

```bash
python -m compileall -q source
python -m unittest discover -s tests/languages
python -m unittest \
  tests.framework.test_adapter_contract \
  tests.test_adapter_framework \
  tests.test_multi_repo_identity \
  tests.test_packaging_metadata \
  tests.metrics.test_yaml_shapes \
  tests.metrics.test_dimension_classifier
```

Run adapter-specific tests for the new language or file-format adapter. Run
`python -m unittest discover -s tests` as a wider regression check when the
repository baseline is green. If the baseline has unrelated known failures,
record those separately instead of treating them as new-language failures.

Run product validation only when the change is expected to affect query
behavior or product-facing packets:

```bash
python -m source.scripts.run_product_validation
```

For parser-backed languages with optional dependencies, ensure tests either
install the extra in CI or skip clearly when the extra is missing.
