# New Language Template

Copy this directory, including `__init__.py`, to
`source/kg/languages/<language_name>/`.

Checklist:

1. Update `files.py` with the language name, aliases, source extensions, manifest files, and `matches_file(path)`.
2. Keep `files.py` free of extractor, adapter, and `RepoSnapshot` imports.
3. Update `language.py` with parser, adapter, source-root, and known-stack wiring.
4. Keep `__init__.py` so packaging and module discovery include the new language directory.
5. Add dimension rules, known-stack metadata, package resolver and
   consumer-manifest hooks when the ecosystem has packages, opportunity
   detectors for measured predicates, and explicit coverage rows for unsupported
   or partial shapes.
6. Add focused tests under `tests/languages/`, plus coverage metric tests when
   dimension classification, opportunities, package manifests, or coverage rows
   are affected.
7. Run `python3 -m unittest discover -s tests/languages` and
   `python3 -m unittest tests.metrics.test_dimension_classifier`.

Unknown or unsupported source shapes should produce coverage gaps rather than invented KG facts.
