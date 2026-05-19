# JS/TS Endpoint Remaining Gaps Debate Seed

Use this as the seed for the next debate after Debate 1.

## Context

Debate 1 made JS/TS endpoint extraction stricter and more trustworthy. The extractor now fails closed instead of emitting unsafe `CALLS_ENDPOINT` facts when it cannot prove the endpoint target.

The LatticeAI 23-repo validation showed the remaining large JS/TS endpoint gaps are:

| Gap | Count | Meaning |
|---|---:|---|
| `target_dynamic_template_segment` | 245 | Path contains dynamic template segments we do not normalize yet. |
| `host_env_backed` | 211 | Path is known, but host/base URL comes from env/config and is not linked to a service. |
| `target_helper_call_deferred` | 39 | Target is built by a helper or URL-construction expression we do not evaluate yet. |

Cross-file imported constants should not be the next focus unless new evidence shows they dominate unresolved rows. The current evidence points to dynamic templates, env-host/base-client provenance, and helper-built URLs.

## Gap 1: Dynamic Template Segments

This means the extractor sees an endpoint-like path, but part of the path is dynamic.

Example:

```ts
api.get(`/campaigns/${campaignId}/analytics/`)
```

Likely normalized endpoint:

```text
/campaigns/{campaignId}/analytics/
```

Why it is currently a gap:

- The extractor can see the static path frame.
- The expression inside `${...}` may be an ID, slug, object property, helper call, or arbitrary code.
- Emitting `/campaigns/{}/analytics/` or guessing the parameter name would create low-quality KG facts.

Debate question:

Can we safely normalize template expressions into route parameters when the static path frame is clear?

Possible narrow rule:

- Allow template literals where every dynamic segment is inside a path segment.
- Use a stable placeholder such as `{param}` or `{campaignId}` only when the expression is a simple identifier/property.
- Fail closed for expressions with helper calls, arithmetic, conditionals, or multiple dynamic pieces in one segment.

## Gap 2: Env-Backed Hosts

This means the extractor knows the endpoint path, but the base URL or host comes from environment/config.

Example:

```ts
const api = axios.create({
  baseURL: import.meta.env.VITE_API_ROOT
})

api.get('/api/token/')
```

What we know:

```text
path = /api/token/
host = ${env:VITE_API_ROOT}
```

What we do not know yet:

```text
Which backend service does VITE_API_ROOT point to?
Which deploy environment defines it?
Is it connected to Terraform, Kubernetes, .env, CI config, or runtime config?
```

Why it is currently a gap:

- The endpoint path is useful but not enough for cross-service linkage.
- Without env/base-client provenance, the KG cannot confidently connect frontend calls to backend endpoints.

Debate question:

Can we trace env-backed base URLs to repo-local config evidence in a general way?

Possible narrow rule:

- Resolve env vars from known local config sources such as `.env*`, Vite config, Next config, Docker Compose, Kubernetes manifests, Terraform outputs/vars, or deployment config.
- Emit provenance evidence even if the final service link remains candidate-only.
- Keep `host_env_backed` when the env var is found but cannot be linked to a service.

## Gap 3: Helper-Built Targets

This means the target URL is produced by a helper function or URL-construction expression.

Examples:

```ts
const url = makeApiUrl('campaigns/widget_activity/')
fetch(url)
```

```ts
fetch(new URL('campaigns/widget_activity/', apiBase).toString())
```

Why it is currently a gap:

- Evaluating arbitrary helpers would turn the extractor into a JavaScript interpreter.
- Helper functions can hide conditionals, config reads, mutation, string transforms, or cross-file imports.
- A broad implementation would likely create false positives.

Debate question:

Can we support a very small helper/URL-constructor algebra without evaluating arbitrary JavaScript?

Possible narrow rule:

- Support `new URL(staticPath, staticOrEnvBase).toString()` when both arguments resolve under the existing safe algebra.
- Support tiny local wrapper functions only when the function body is a direct return of a safe expression and has no branching, mutation, or external reads.
- Fail closed for cross-file helpers unless a later debate adds exported binding/function summaries.

## Recommended Debate Focus

The next debate should decide the safest first slice among:

1. Dynamic template normalization for route-like path segments.
2. Env-host/base-client provenance from local config.
3. Narrow `new URL(...)` and direct-return helper support.

Recommended order:

1. Start with dynamic template normalization because it is the largest bucket and can improve endpoint facts without needing cross-repo provenance.
2. Then tackle env-host provenance because it improves graph linkage quality.
3. Treat helper support as narrow and conservative; only implement if the debate defines a tiny safe algebra.

## Non-Goals

- No repo-specific rules for LatticeAI or Mercury.
- No arbitrary JavaScript interpretation.
- No cross-file imported-constant work unless evidence changes.
- No service-link promotion without provenance evidence.
- No fabricated endpoint facts when a path cannot be proven.
