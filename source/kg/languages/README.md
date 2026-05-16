# Language Extractor Modules

Each supported source language owns one directory under `source/kg/languages/`.

Required files:

- `files.py` exports `LANGUAGE_FILES`. This must be lightweight and import-safe for repo discovery. Do not import extractors, adapters, or `RepoSnapshot` here.
- `language.py` exports `LANGUAGE_SUPPORT`. This can import extractors and adapters.

`files.py` is used to bucket repository files without loading extractor code. `language.py` is used by build and extraction paths to collect adapters, known-stack mappings, and language-owned source-root data.

To add a language, copy `_template/`, rename the package, fill in `files.py` and `language.py`, then run:

```bash
python3 -m unittest discover -s tests/languages
python3 -m unittest discover -s tests
```
