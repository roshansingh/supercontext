# Debate Seed: Cross-Repo Kubernetes Env Host Linkage

## Question

Can we reduce `host_env_backed` endpoint gaps by linking env-backed endpoint calls in application repos to Kubernetes, ConfigMap, Secret, Helm, or Kustomize configuration in separate infrastructure repos?

This should improve the KG in a repo-agnostic way. The goal is not to hardcode LatticeAI conventions or guess hosts from variable names alone.

## Directional Guardrail

This debate should not start from "how do we eliminate every remaining LatticeAI gap?" That path can become an endless spiral because every repo has different helper names, deployment conventions, config layouts, and historical quirks.

The right bar is:

1. The implementation handles a common software pattern, not a repo-specific shape.
2. It converts uncertainty into structured evidence, not blind facts.
3. It improves a durable KG surface that many OSS users will have: source code, env/config, deployment/IaC, package/deployable identity, and endpoint host provenance.

The debate should prefer provenance/linkage over more syntax edge cases. A good result may still leave `host_env_backed` rows in the report, but those rows should become more useful: linked to a Deployment, ConfigMap, Secret, Helm value, Kustomize overlay, environment, or explicit ambiguity reason.

Do not treat every coverage row as a bug. Many rows mean "the KG needs more evidence before making a safe conclusion." Those should become better caveats and evidence links, not forced endpoint facts.

## Current Problem

The latest 23-repo LatticeAI coverage run after Debate 3 still has `576` coverage-gap rows. The largest remaining endpoint caveat is:

- `host_env_backed`: `275`

This means we often know the endpoint path, but not the concrete host/base URL. Example shape:

```ts
const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });
api.get("campaigns/customer_support/get_tickets/");
```

Today the KG can represent:

- endpoint path: `/campaigns/customer_support/get_tickets/`
- host: `${env:VITE_API_ROOT}`
- env reference: `VITE_API_ROOT`

But it usually cannot say:

- which deployment supplies `VITE_API_ROOT`
- which config file defines it
- whether the value is `https://api.example.com`
- whether that host belongs to the same product system

## Why Kubernetes/IaC May Help

In many organizations, app repos do not contain their runtime config. A separate deployment/config repo often contains Kubernetes manifests like:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mercury-ui
  namespace: production
  labels:
    app: mercury-ui
spec:
  template:
    spec:
      containers:
        - name: mercury-ui
          image: ghcr.io/latticeai/mercury_ui:abc123
          env:
            - name: VITE_API_ROOT
              value: https://api.example.com
```

This gives useful linking evidence:

- deployable identity: `mercury-ui`
- namespace/environment: `production`
- container/image: `ghcr.io/latticeai/mercury_ui:abc123`
- env var definition: `VITE_API_ROOT`
- env var value: `https://api.example.com`

If an application repo uses `VITE_API_ROOT`, and a deployment repo defines `VITE_API_ROOT` for a deployable/image that can be linked back to that app, then the KG can attach stronger evidence to the env-backed endpoint host.

## Important Caveat

Same env var name is not enough.

This is unsafe:

```text
frontend repo uses API_HOST
deployment repo defines API_HOST
therefore they match
```

`API_HOST`, `BASE_URL`, `VITE_API_ROOT`, and similar names can appear in many repos, services, and environments. A safe linker needs provenance.

Good evidence can include:

- same deployable/service name
- container image pointing to the source repo or package
- labels/annotations that name the app/repo/service
- namespace/environment qualifiers
- Helm release/chart values connected to a specific deployment
- Kustomize overlay path such as `overlays/prod/mercury-ui`
- ConfigMap/Secret referenced by a specific Deployment container

## Config Patterns To Handle

### Direct Deployment Env Value

```yaml
containers:
  - name: web
    image: ghcr.io/acme/web:sha123
    env:
      - name: VITE_API_ROOT
        value: https://api.acme.com
```

Potential KG output:

- `Deployment` or `Deployable` for `web`
- `Environment` for namespace/overlay if known
- `REFERENCES_ENV_VAR(name=VITE_API_ROOT, reference_kind=deployment_env_definition)`
- optionally link env value to `Domain(api.acme.com)`

### ConfigMap Key Reference

```yaml
env:
  - name: VITE_API_ROOT
    valueFrom:
      configMapKeyRef:
        name: web-config
        key: VITE_API_ROOT
```

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
data:
  VITE_API_ROOT: https://api.acme.com
```

Potential behavior:

- Link Deployment env usage to ConfigMap key definition.
- Resolve concrete value only if the ConfigMap is found in the same namespace/overlay scope.
- If multiple ConfigMaps match, fail closed and keep host env-backed.

### Secret Key Reference

```yaml
env:
  - name: API_TOKEN
    valueFrom:
      secretKeyRef:
        name: web-secrets
        key: API_TOKEN
```

Potential behavior:

- Do not invent secret values.
- Emit provenance that Deployment supplies `API_TOKEN` from `Secret/web-secrets`.
- Keep any endpoint host unresolved unless a non-secret value is available.

### EnvFrom

```yaml
envFrom:
  - configMapRef:
      name: web-config
  - secretRef:
      name: web-secrets
```

Potential behavior:

- Link all ConfigMap keys as possible env definitions for that container.
- Secret keys may be known only if the Secret manifest contains key names.
- If exact env var key cannot be proven, keep host env-backed.

### Helm Values

```yaml
# deployment.yaml
env:
  - name: VITE_API_ROOT
    value: {{ .Values.apiRoot | quote }}
```

```yaml
# values-prod.yaml
apiRoot: https://api.acme.com
```

Potential behavior:

- Parse common Helm value references if safe and local to the chart.
- Link `.Values.apiRoot` to values files by chart/release/overlay context.
- Fail closed on complex templates, functions, conditionals, or missing values.

### Kustomize Overlays

```yaml
# overlays/prod/kustomization.yaml
configMapGenerator:
  - name: web-config
    literals:
      - VITE_API_ROOT=https://api.acme.com
```

Potential behavior:

- Treat overlay path as environment evidence.
- Generate config definitions from `configMapGenerator`.
- Link them to Deployments in the same overlay when referenced.

## Product Decision Needed

There are two possible levels of support.

### Level 1: Provenance Only

Keep endpoint host as `${env:VITE_API_ROOT}`, but attach evidence:

```text
This env var is supplied by:
Deployment mercury-ui
namespace production
ConfigMap web-config
key VITE_API_ROOT
value present: yes/no
```

This is safer and already useful for answers like:

> Where does this API host come from?

### Level 2: Host Resolution

If the config value is concrete and provenance is unambiguous, promote:

```text
${env:VITE_API_ROOT} -> https://api.acme.com
```

Then endpoint calls can have a concrete host:

```text
CALLS_ENDPOINT host=api.acme.com path=/campaigns/customer_support/get_tickets/
```

This should only happen when:

- exactly one matching config definition is found
- deployment/config environment is known or unambiguous
- deployable/app identity can be linked to the source repo
- value is a concrete URL or host
- value is not secret-only

## Suggested Debate Scope

The debate should decide the smallest useful OSS implementation.

Recommended PR sequence:

1. **Kubernetes config extractor taxonomy**
   - Parse Deployment/StatefulSet/CronJob containers.
   - Extract container image, env entries, `envFrom`, ConfigMap refs, Secret refs, namespace, labels.
   - Parse ConfigMap key/value pairs.
   - Emit coverage for unsupported/ambiguous cases, not junk facts.

2. **Cross-repo env definition linkage**
   - Link app env usage to deployment env definitions only with provenance.
   - Use repo/deployable/image/label/environment evidence.
   - Do not match by env var name alone.

3. **Safe host resolution**
   - Resolve concrete host only when the config value is non-secret and unambiguous.
   - Preserve `host_env_backed` when value is missing, secret, templated, or ambiguous.

4. **Coverage/report improvements**
   - Split `host_env_backed` into more useful sub-states if needed:
     - env var has no definition found
     - env var definition found but value hidden
     - env var definition found but ambiguous
     - env var value resolved to concrete host
   - Avoid adding new reason strings unless code emits them from explicit branches.

## Non-Goals

- No repo-specific hostname allowlists.
- No matching by env var name alone.
- No resolving Secret values unless the value is explicitly present and safe to read.
- No arbitrary Helm template execution.
- No broad Terraform/Kubernetes inventory modeling beyond product-relevant config, deployable, environment, endpoint host, domain, and evidence links.
- No changing canonical ontology unless existing `Deployable`, `Deployment`, `Environment`, `Domain`, `Endpoint`, and env-reference facts cannot represent the result.

## Success Metrics

After implementation, rerun the 23-repo coverage report and compare:

- `host_env_backed` count
- number of env-backed endpoints linked to a deployment/config source
- number of env-backed endpoints safely resolved to concrete host
- `CALLS_ENDPOINT` facts with concrete host
- ambiguity/secret/templated config coverage rows

Expected good result:

- Not necessarily a huge drop in total `coverage_gap_count`.
- Clear movement from “env host unknown” to “env host linked to deployment/config evidence.”
- Some concrete host resolution where Kubernetes/ConfigMap values are explicit and unambiguous.

## Core Debate Question

What is the minimal safe implementation that turns env-backed endpoint hosts from loose caveats into deployment/config-linked KG evidence across repos, without overfitting to one organization or inventing unsafe host mappings?
