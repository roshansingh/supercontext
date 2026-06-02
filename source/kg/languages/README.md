# Language Extractor Modules

Each supported source language owns one directory under `source/kg/languages/`.

Required files:

- `files.py` exports `LANGUAGE_FILES`. This must be lightweight and import-safe for repo discovery. Do not import extractors, adapters, or `RepoSnapshot` here.
- `language.py` exports `LANGUAGE_SUPPORT`. This can import extractors and adapters.

`files.py` is used to bucket repository files without loading extractor code. `language.py` is used by build and extraction paths to collect adapters, known-stack mappings, and language-owned source-root data.

Coverage metrics stay language-neutral. A language is responsible for the
inputs that make those metrics useful: dimension rules, known-stack metadata,
package resolver and consumer-manifest hooks for package ecosystems,
opportunity detectors for measured gaps, and explicit coverage rows for
unsupported or partial source shapes. See
`docs/contributing/ADDING-A-NEW-LANGUAGE.md` before adding or widening a
language.

To add a language, copy `_template/`, rename the package, fill in `files.py`
and `language.py`, then run the focused checks:

```bash
python3 -m unittest discover -s tests/languages
python3 -m unittest tests.test_adapter_framework tests.test_multi_repo_identity
python3 -m unittest tests.metrics.test_dimension_classifier
python3 -m source.scripts.run_product_validation
```

Run `python3 -m unittest discover -s tests` as a wider regression check when
the repository baseline is green. If the baseline has unrelated known failures,
record those separately instead of treating them as new-language failures.
