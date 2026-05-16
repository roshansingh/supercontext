# New Language Template

Copy this directory to `source/kg/languages/<language_name>/`.

Checklist:

1. Update `files.py` with the language name, aliases, source extensions, manifest files, and `matches_file(path)`.
2. Keep `files.py` free of extractor, adapter, and `RepoSnapshot` imports.
3. Update `language.py` with parser, adapter, source-root, and known-stack wiring.
4. Add focused tests under `tests/languages/`.
5. Run `python3 -m unittest discover -s tests/languages`.

Unknown or unsupported source shapes should produce coverage gaps rather than invented KG facts.
