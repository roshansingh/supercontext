# Cross-Repo Package Linkage Debate Seed

## Why This Matters

The KG can answer single-repo questions reasonably well, but cross-repo dependency answers are still weak. In the latest LatticeAI 23-repo run, the snapshot had 937 `ExternalPackage` entities and only 2 `RESOLVES_TO_REPO` facts. That does not mean 935 links are definitely missing: many packages are stdlib, builtins, or third-party libraries. It does mean our current metric and linker do not yet separate "not supposed to link" from "probably internal but unresolved" cleanly enough.

The goal is not to overfit LatticeAI. The goal is to make BetterContext better at fleet-level OSS questions such as:

- "Which repos depend on this internal library?"
- "If this package changes, which services might break?"
- "Which imports look internal but are not linked to a repo?"
- "Is this dependency third-party, builtin, or another repo in this fleet?"

## Current Code Shape

Today, cross-repo linking is mostly implemented as a package-provider projection:

- `source/kg/build/relink.py` loads repo snapshots, builds package providers from language manifests, and writes `_fleet/cross_repo_links.jsonl`.
- `source/kg/build/relink.py` emits `RESOLVES_TO_REPO` and `RESOLVES_TO_SERVICE` when an `ExternalPackage` can be matched to one provider repo.
- `source/kg/languages/*/package_resolver.py` provides language-specific provider metadata for Python, TypeScript, and .NET.
- `source/kg/languages/types.py` exposes `LanguageSupport.package_resolver()` as the language hook.
- `source/kg/metrics/compute.py` computes `M_cross_repo_linkage` from all `ExternalPackage` entities divided by subjects with `RESOLVES_TO_REPO`.

This is a good modular start: the linker is centralized, and provider metadata is language-specific. The weak spot is that the linker mainly matches observed imports against provider aliases. It does not yet model consumer dependency manifests as first-class evidence.

## Problem

The current denominator for `M_cross_repo_linkage` is too broad. It counts every `ExternalPackage`, including packages that should never resolve to a repo in the scanned fleet.

Examples:

```python
import os
import json
import boto3
import requests
import shared_billing
```

Only `shared_billing` is likely a fleet-internal package. `os` and `json` are stdlib. `boto3` and `requests` are third-party. Counting all five against cross-repo linkage makes the metric noisy and makes improvement look smaller or larger for the wrong reasons.

The linker also misses strong consumer-side evidence that often exists in manifests:

```json
{
  "dependencies": {
    "@acme/shared-ui": "workspace:*",
    "@acme/payments-client": "git+https://github.com/acme/payments-client.git",
    "react": "^18.2.0"
  }
}
```

Here `@acme/shared-ui` and `@acme/payments-client` are much stronger cross-repo candidates than `react`. A good linker should use that manifest evidence directly instead of relying only on imports observed in code.

## Proposed Direction

### PR 1: Make the Metric Denominator Honest

Change `M_cross_repo_linkage` so the denominator is "candidate internal package references" instead of every `ExternalPackage`.

Classify package references into buckets:

- `builtin_or_stdlib`
- `known_third_party`
- `consumer_manifest_external`
- `candidate_internal`
- `candidate_internal_ambiguous`
- `unknown`

Metric behavior:

- `builtin_or_stdlib` should not count against cross-repo linkage.
- obvious third-party packages should not count against cross-repo linkage.
- `candidate_internal` should count in the denominator.
- unresolved `candidate_internal` should produce coverage gaps.
- `unknown` should be reported separately, not silently treated as internal.

This makes the metric more truthful before trying to improve the linker.

### PR 2: Extract Consumer Dependency Manifest Evidence

Add structured dependency-manifest extraction for consumers, not only provider package metadata.

Start with high-signal sources:

- JavaScript/TypeScript: `package.json` `dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies`, workspace specs, `file:` specs, and git URL specs.
- Python: `pyproject.toml`, `requirements.txt`, and path or git dependencies where statically visible.
- .NET: `ProjectReference` and package/project identity from `.csproj`.

Example:

```xml
<ItemGroup>
  <ProjectReference Include="../Shared/Shared.csproj" />
  <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
</ItemGroup>
```

`ProjectReference` is a strong internal dependency signal. `Newtonsoft.Json` is third-party and should not count as a missing cross-repo link.

### PR 3: Add Repo-Identity Linkage From Manifest URLs And Paths

When a dependency spec points to a repo URL or local path, normalize it into repo identity evidence.

Examples:

```json
{
  "dependencies": {
    "@acme/client": "git+ssh://git@github.com/acme/client.git",
    "@acme/shared": "file:../shared"
  }
}
```

Desired behavior:

- `github.com/acme/client` links to the matching scanned repo identity if present.
- `file:../shared` links only if the path resolves to a scanned repo snapshot.
- ambiguous or missing providers emit coverage rows instead of guessed links.

### PR 4: Improve Provider Aliases, But Keep Them Source-Backed

Expand provider aliases only from source-of-truth metadata:

- TypeScript `package.json` package name and workspace package roots.
- Python project name plus package roots from `pyproject.toml` / setup metadata where statically available.
- .NET `PackageId`, `AssemblyName`, `RootNamespace`, project file name, and project references.

Do not infer aliases from arbitrary repo name similarity unless there is explicit config or manifest evidence.

### PR 5: Add Coverage Rows For Linkage Failure Modes

Add coverage reasons that tell users what is missing without pretending to know the answer:

- `cross_repo_dependency_no_provider`
- `cross_repo_dependency_ambiguous_provider`
- `cross_repo_dependency_external_third_party`
- `cross_repo_dependency_builtin_or_stdlib`
- `cross_repo_dependency_unknown_category`
- `cross_repo_dependency_manifest_unreadable`

This helps the coverage report explain whether a repo has a real KG gap, an unsupported manifest shape, or simply many third-party dependencies.

## Non-Goals

- Do not fuzzy-match package names to repo names without manifest or config evidence.
- Do not add org-specific allowlists.
- Do not treat every `@company/*` or company-prefixed package as internal unless the package is backed by scanned repo metadata, workspace config, git URL, local path, or explicit user config.
- Do not resolve arbitrary third-party packages to public repositories.
- Do not force every unresolved package into `RESOLVES_TO_REPO`; unresolved but well-classified evidence is better than wrong KG facts.

## Success Criteria

The implementation is successful if:

- `M_cross_repo_linkage` stops penalizing stdlib, builtin, and obvious third-party packages.
- The report shows candidate internal dependency coverage separately from all external imports.
- More `RESOLVES_TO_REPO` facts come from manifest-backed evidence, not name guessing.
- Ambiguous internal candidates produce explainable coverage rows.
- Queries about repo-to-repo dependency impact improve across arbitrary multi-repo fleets, not only the LatticeAI 23 repos.

## Example Expected Output

Given repos:

```text
api/
  package.json: depends on "@acme/shared": "workspace:*"

shared/
  package.json: name "@acme/shared"
```

Expected KG:

```text
ExternalPackage("@acme/shared")
Repo("shared")
ExternalPackage("@acme/shared") RESOLVES_TO_REPO Repo("shared")
```

Expected metric interpretation:

```text
candidate_internal: 1
resolved_internal: 1
M_cross_repo_linkage: 1.0
```

Given:

```python
import os
import requests
import internal_client
```

Expected metric interpretation:

```text
builtin_or_stdlib: os
known_third_party: requests
candidate_internal_or_unknown: internal_client
```

Only `internal_client` should be considered a linkage candidate unless stronger metadata proves otherwise.
