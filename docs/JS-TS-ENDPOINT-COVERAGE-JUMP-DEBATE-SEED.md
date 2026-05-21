# JS/TS Endpoint Coverage Jump Debate Seed

Use this as the seed for the next debate after Debate 2.

## Why This Exists

Debate 2 improved correctness, but it did not produce the coverage jump we expected.

Before Debate 2, the LatticeAI 23-repo report had three large JS/TS endpoint gaps:

| Gap | Count |
|---|---:|
| `target_dynamic_template_segment` | 245 |
| `host_env_backed` | 211 |
| `target_helper_call_deferred` | 39 |

After Debate 2:

| Signal | Before | After | Movement |
|---|---:|---:|---:|
| `CALLS_ENDPOINT` facts | 215 | 242 | +27 |
| `helper_inline` endpoint facts | 0 | 13 | +13 |
| `template_parameterized` endpoint facts | 0 | 14 | +14 |
| Fleet score | 0.4167 | 0.4215 | +0.0048 |
| Coverage gap count | 576 | 576 | 0 |

This is useful, but it is not enough. The debate should start from this lesson: we spent too much complexity on narrow URL/helper edge cases and did not attack the dominant frontend shape.

## Non-Negotiable Scope

The next proposal must improve the OSS extractor generally. Do not add LatticeAI-, Mercury-, ShopAgain-, or repo-specific checks.

Do not solve this by matching file names, service names, route prefixes, app names, or known constants from one customer repo.

The work should be justified by common JS/TS frontend patterns:

- configured HTTP clients such as Axios instances,
- relative paths passed to known client methods,
- module-local path root constants,
- exported client/path helper summaries,
- safe template parameterization under a known client/base context.

If a proposed rule would not make sense in a random React/Vite/Next/Vue/Axios codebase, it is out of scope.

## Where Debate 2 Was Too Narrow

Debate 2 assumed many `target_dynamic_template_segment` rows were directly normalizable into absolute paths.

Example that Debate 2 handles:

```ts
api.get(`/campaigns/${campaignId}/analytics/`)
```

Output:

```text
/campaigns/{campaignId}/analytics/
```

But many real frontend calls are relative paths under a configured HTTP client:

```ts
const api = axios.create({
  baseURL: import.meta.env.VITE_API_ROOT,
});

api.get(`campaigns/customer_support/${ticketId}/close_ticket/`);
```

The path is meaningful because `api` supplies the base URL. Debate 2 saw the template string itself and treated the dynamic segment as host-position because the string did not start with `/`.

That was safe, but too conservative for client-method context.

## Biggest High-Leverage Idea

The next debate should focus on **client-context-aware endpoint resolution**.

Today, the resolver mostly asks:

```text
Can this target expression prove a standalone endpoint path?
```

It should also ask:

```text
Is this target expression passed to a known HTTP client whose base URL/host context is already known?
```

If yes, then relative paths like `campaigns/${id}/` are path-relative, not host-position.

This is a general OSS improvement because most frontend apps use configured clients:

```ts
const client = axios.create({ baseURL: process.env.API_BASE_URL });
client.get(`users/${userId}/orders/`);
```

```ts
const api = ky.create({ prefixUrl: import.meta.env.VITE_API_ROOT });
api.post(`projects/${projectId}/runs`);
```

```ts
export const http = axios.create({ baseURL: config.apiUrl });
http.delete(`teams/${teamId}/members/${memberId}`);
```

The extractor should not require these relative target strings to start with `/` when they are arguments to a known base-backed client method.

## Proposed Debate Focus

### 1. Add Client Context To Target Resolution

For known HTTP-client call sites, pass a target context into endpoint expression resolution:

```text
target_context = {
  call_transport: "axios" | "fetch" | "ky" | ...,
  client_name: "api",
  path_mode: "client_relative_allowed",
  base_kind: "literal" | "env" | "unknown",
}
```

Then a template like this:

```ts
api.get(`campaigns/${campaignId}/stats/`);
```

can resolve as:

```text
path = /campaigns/{campaignId}/stats/
host = env-backed or unknown from api base
route_params = ["campaignId"]
resolution_kind = "template_parameterized"
host_resolution_kind = "env_backed_unresolved" when base is env-backed
```

This should reuse the Debate 2 template parameterization code. The key change is not a new template algorithm. The key change is the context that says a relative path is valid because it is being sent through a known client.

Fail closed when:

- the callee is not a known HTTP client method,
- the target could be a full host or scheme expression,
- the client base is shadowed or ambiguous,
- the target is a whole dynamic value such as `api.get(path)`,
- the template expression is unsafe under the existing Debate 2 rules.

### 2. Resolve Module-Local Path Root Constants

Many frontend service files define path roots once and reuse them:

```ts
const campaignsRoot = "campaigns/";
const popupsRoot = "campaigns/popups/";

api.get(`${campaignsRoot}${campaignId}/`);
api.post(`${popupsRoot}${popupId}/publish/`);
```

This should not require a new JavaScript interpreter. It should reuse the existing safe expression algebra:

- literal strings,
- simple `const` aliases,
- string concatenation,
- safe template parameterization,
- source-order and shadowing checks,
- fail-closed mutation/reassignment handling.

Expected safe output:

```text
/campaigns/{campaignId}/
/campaigns/popups/{popupId}/publish/
```

Another common shape:

```ts
const root = "audience/";
const listRoot = root + "list/";

api.get(`${listRoot}${listId}/`);
```

Expected output:

```text
/audience/list/{listId}/
```

This is a broad OSS improvement because service modules commonly use root constants to avoid repeating route prefixes.

### 3. Handle Conditional Literal Roots Carefully

Some apps use environment or role-dependent literal roots:

```ts
const campaignsRoot = isAdminApp ? "admin_user/campaigns/" : "campaigns/";

api.get(`${campaignsRoot}${campaignId}/`);
```

This is high value but needs a clear contract.

Possible debate options:

1. Emit multiple endpoint facts when every branch is a literal path root:

```text
/admin_user/campaigns/{campaignId}/
/campaigns/{campaignId}/
```

2. Emit no endpoint fact but emit a specific coverage reason:

```text
target_conditional_literal_union
```

3. Emit a single abstract path only if the ontology/query layer explicitly supports alternatives.

Do not silently choose the first branch. That would be wrong.

### 4. Add Exported Client Summaries Before Cross-File Constant Chasing

Many repos define a configured client in one file and use it elsewhere:

```ts
// api.ts
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_ROOT,
});
```

```ts
// users.ts
import { api } from "./api";

api.get(`users/${userId}/`);
```

This is more important than arbitrary cross-file constant resolution. The summary should be narrow:

```text
ExportedHttpClientSummary {
  export_name: "api",
  transport: "axios",
  base_kind: "env",
  env_names: ["VITE_API_ROOT"],
}
```

Then imports can use that summary to mark relative endpoint targets as client-relative.

This is general OSS value. It applies to Axios, Ky, Got, custom fetch wrappers, and generated API clients when the client factory is recognizable.

Do not start by resolving arbitrary imported constants like:

```ts
import { campaignsRoot } from "./routes";
```

That is a broader module-summary problem. Start with exported HTTP clients because they directly explain endpoint host/path context.

### 5. Consider Small, Reusable Path Helper Summaries Later

Only after client context and local path roots, consider path helper summaries.

Safe helper shape:

```ts
const getBillingUrl = (path: string) => `billing/${path}`;

api.get(getBillingUrl(`plans/${planId}/`));
```

Expected output:

```text
/billing/plans/{planId}/
```

But this should reuse the Debate 2 direct-return helper algebra. Do not expand into arbitrary helper interpretation.

The important distinction:

- Good: summarize pure direct-return path helpers.
- Bad: interpret application logic, conditionals, loops, mutation, or external runtime state.

## What Not To Do Next

Do not spend another large PR on rare URL-constructor edge cases unless coverage evidence shows they dominate.

Low-priority examples:

```ts
new URL(path, base).pathname
new URL(path, base).href
someHelper().toString()
window.location.origin edge cases
```

These may be useful eventually, but Debate 2 showed that narrow helper/URL algebra moves too little by itself.

Do not add report-specific allowlists such as:

```text
if repo == "mercury_ui" and variable ends with Root
```

That is explicitly out of scope.

## How To Measure Success

Do not judge this only by fleet score. Fleet score is diluted by cross-repo linkage, unsupported languages, dimension classification, and other metrics.

Use these additional general metrics:

| Metric | Why |
|---|---|
| New `CALLS_ENDPOINT` facts from client-relative targets | Directly measures endpoint extraction gain |
| Reduction in `template_dynamic_host_position` | Shows relative templates are now understood under client context |
| Reduction in `host_env_backed` only when host provenance improves | Avoids pretending env-backed paths are fully linked |
| Count of resolved paths with `route_params` | Shows dynamic routes became queryable |
| Number of repos/files improved | Guards against repo-specific overfitting |
| False-positive regression suite | Proves we did not fabricate endpoints |

Expected success should be framed as:

```text
We converted common client-relative frontend endpoint calls into grounded endpoint facts.
```

Not:

```text
Fleet score will jump dramatically.
```

## Suggested PR Sequence

### PR-1: Client-Relative Path Context

Goal: allow relative path strings/templates when passed to known configured HTTP clients.

Implement:

- add target-resolution context for known HTTP client method calls,
- allow relative static and parameterized template paths in that context,
- preserve `host_env_backed` when base URL is env-backed,
- keep existing fail-closed behavior for unknown callees.

Example:

```ts
const api = axios.create({ baseURL: import.meta.env.API_ROOT });
api.get(`campaigns/${campaignId}/`);
```

Expected:

```text
CALLS_ENDPOINT path=/campaigns/{campaignId}/
REFERENCES_ENV_VAR name=API_ROOT
coverage may still include host_env_backed because service target is not known
```

### PR-2: Module-Local Path Root Algebra

Goal: resolve common path root constants without arbitrary interpretation.

Implement:

- literal `const` path roots,
- chained literal concatenation,
- template roots under client-relative context,
- route params through root + dynamic suffix.

Example:

```ts
const root = "audience/";
const listRoot = root + "list/";
api.get(`${listRoot}${listId}/`);
```

Expected:

```text
/audience/list/{listId}/
```

### PR-3: Exported HTTP Client Summaries

Goal: use configured clients across files without chasing arbitrary constants.

Implement:

- summarize exported Axios/Ky/Got clients,
- resolve imports of those summaries,
- pass client context to call-site extraction in consumer files.

Example:

```ts
// api.ts
export const api = axios.create({ baseURL: process.env.API_ROOT });

// users.ts
import { api } from "./api";
api.get(`users/${userId}/`);
```

Expected:

```text
/users/{userId}/ with env-host provenance
```

## Acceptance Bar

The debate should reject proposals that only add more edge cases.

A good implementation should:

- reuse Debate 1 and Debate 2 safe expression resolution,
- make client context explicit instead of hidden in string heuristics,
- improve multiple repos/files without repo-name allowlists,
- keep env-backed hosts partial unless they can be linked to a service with real provenance,
- add before/after evidence for gap movement and newly extracted endpoint facts,
- include negative tests for unknown clients, shadowed clients, unsafe templates, ambiguous roots, and conditional roots.

The likely winning thesis:

```text
Coverage jumps when the extractor understands the HTTP client context around a target expression, not when it evaluates more isolated JavaScript expressions.
```
