# ADR-0011: Use Declared- and Metadata-Backed Python Import Distribution Aliases

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

Python import roots do not always match PyPI distribution names. Examples include `sklearn` for `scikit-learn`, `PIL` for `Pillow`, `bs4` for `beautifulsoup4`, and `cv2` for OpenCV distributions.

The KG already records import facts with `category`, `import_root`, and `distribution_name`. Product query Q012 exposed a generic gap: `sklearn` importers were found, but dependency metadata could not prove the `scikit-learn` distribution mapping, so the query remained partial.

## Decision

Python import normalization uses this precedence:

1. Internal module detection.
2. Standard-library detection.
3. Direct declared dependency match when the import root already matches the declared package name.
4. `importlib.metadata.packages_distributions()` candidates, preferring the candidate that matches a declared dependency.
5. A single unambiguous `importlib.metadata.packages_distributions()` candidate.
6. A small curated fallback map for stable import-root-to-distribution aliases, using declared dependencies to disambiguate multi-candidate aliases.
7. Existing runtime `find_spec` fallback for installed packages whose distribution name remains unknown.

The fallback map is a normalizer concern, not query-specific logic. It may include only widely known Python packaging aliases where the import root is stable and the distribution mismatch is common.

Ambiguous aliases must fail closed unless the repo's declared dependencies select exactly one candidate. For example, `cv2` may map to several OpenCV distributions; if `opencv-python-headless` is declared, use it. If no declared dependency disambiguates the candidate set, do not guess.

The accepted v0 alias set is:

| Import root | Distribution candidates |
|---|---|
| `attr` | `attrs` |
| `bs4` | `beautifulsoup4` |
| `cv2` | `opencv-python`, `opencv-python-headless`, `opencv-contrib-python` |
| `dateutil` | `python-dateutil` |
| `PIL` | `Pillow` |
| `pkg_resources` | `setuptools` |
| `sklearn` | `scikit-learn` |
| `yaml` | `PyYAML` |

## Consequences

Positive:

- Turns import facts for common Python packages into higher-quality dependency facts.
- Keeps product/evaluation code generic; Q012 improves as a by-product of better normalization.
- Preserves fail-closed behavior for ambiguous package families.

Negative:

- Introduces a curated alias list that requires maintenance.
- Still does not replace per-repo virtualenv/package-lock resolution.

## Implementation Status

Implemented in `source/kg/normalization/python/imports.py`.

The current curated aliases are intentionally small and must stay covered by tests when changed.

## Relationship to Existing ADRs

- ADR-0008 remains the import-normalization decision. This ADR narrows one Python-specific normalization source.
- ADR-0006 fact metadata still applies: normalized import facts remain deterministic static facts when backed by source imports and normalizer rules.

## References

- `source/kg/normalization/python/imports.py`
- `tests/test_import_normalization.py`
- `docs/evaluation/CANONICAL-VALIDATION-REPORT.md`
