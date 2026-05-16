# Adding a New Language

The language plug-in boundary is intentionally split in two:

- `files.py` is lightweight file discovery. It must not import extractors, adapters, or `RepoSnapshot`.
- `language.py` is full extraction support. It can import parser code, adapters, known-stack mappings, and package-resolution helpers.

This split keeps repo discovery import-safe while still making each language own its extraction behavior.

## Steps

1. Copy `source/kg/languages/_template/` to `source/kg/languages/<language_name>/`.
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
4. Add tests under `tests/languages/`.
5. Run:

```bash
python3 -m unittest discover -s tests/languages
python3 -m unittest discover -s tests
python3 -m source.scripts.run_product_validation
```

Do not add a central adapter registry edit for a language-owned adapter unless it is still part of the legacy compatibility path. New languages should be discovered from their directory.
