# ADR-0010: Represent Deploy Targets Without Domains as Deploy-Only Facts

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

The current KG can extract Apache virtual-host mappings when a config block has both a domain directive and a WSGI entrypoint. Current behavior is intentionally strict:

- `ServerName` / `ServerAlias` plus `WSGIScriptAlias` emits `Domain`, `DeployTarget`, `REFERENCES_DOMAIN`, and `ROUTES_DOMAIN_TO_DEPLOY`.
- `WSGIScriptAlias` without a domain emits nothing.

This avoids inventing a routed domain, but it also means the graph cannot represent useful deploy evidence such as "this service has a WSGI entrypoint configured" when the routing layer is absent from the same file.

The existing `ROUTES_DOMAIN_TO_DEPLOY` relation is semantically a route from a concrete `Domain` to a concrete `DeployTarget`. Allowing missing or nullable domains would make downstream query semantics ambiguous and would let answer synthesis imply reachability that the KG has not proven.

## Decision

Add a separate deploy-only relation when implementation work begins:

`Service -[DEPLOYS_VIA_CONFIG]-> DeployTarget`

This relation means "configuration evidence shows this service is deployed through this target." It does not mean a public domain, route, load balancer, DNS record, or user-reachable endpoint exists.

`ROUTES_DOMAIN_TO_DEPLOY` remains strict:

`Domain -[ROUTES_DOMAIN_TO_DEPLOY]-> DeployTarget`

It must only be emitted when the source evidence contains a concrete domain identity.

## Target Implementation Fact Shape

For Apache/WSGI domainless config, future implementation should emit:

- `DeployTarget` entity using the target identity convention: `{tenant_id, repo, type, target}`. For example, `{tenant_id: "default", repo: "api", type: "wsgi", target: "/srv/app/wsgi.py"}`.
- `DEPLOYS_VIA_CONFIG` fact from the `Service` entity to the deploy target.
- Evidence coordinates for the config line that defines the deploy target.
- Qualifier metadata such as `source_kind: "apache_vhost"`, repo-relative `path`, `entrypoint_kind: "wsgi"`, and optional `route_path: "/"`.

It must not emit:

- a `Domain` entity without `ServerName`, `ServerAlias`, or equivalent routed-domain evidence;
- `ROUTES_DOMAIN_TO_DEPLOY` with a missing, synthetic, or nullable domain.

The subject `Service` follows the existing service-entity convention used by the config extractors: tenant-scoped service identity derived from the repo unless a more specific service identity has already been resolved.

`DeployTarget` identity must be stable within a tenant and repo. The minimum target tuple is `{tenant_id, repo, type, target}`. `type` names the config/deploy family, such as `wsgi`, `systemd_unit`, `procfile_process`, `container_image`, or `k8s_workload`. `target` is the stable family-specific identifier. Additional identity fields may be added by later family-specific extractor ADRs or implementation notes, but the `{tenant_id, repo, type, target}` tuple remains the compatibility contract once implemented.

When both domain and deploy-target evidence exist, the extractor should emit both:

- `DEPLOYS_VIA_CONFIG` for service-to-deploy proof;
- `ROUTES_DOMAIN_TO_DEPLOY` for domain-to-deploy route proof.

Both facts must point to the same `DeployTarget` entity when the underlying target is the same. Query layers must deduplicate deploy-target lists by `DeployTarget` identity. Answer synthesis should prefer the richer routed fact when both are present, while retaining the deploy-only fact as supporting deploy evidence.

Facts emitted by deterministic config extractors should be canonical facts with `derivation_class = deterministic_static`, subject to ADR-0006 promotion and evidence-envelope rules.

## Query Semantics

Runtime-topology answers should distinguish routed deploys from deploy-only evidence:

- Routed deploy: "domain X routes to deploy target Y" with `ROUTES_DOMAIN_TO_DEPLOY` evidence.
- Domainless deploy: "deploy target Y is configured, but no routed domain evidence was found" with `DEPLOYS_VIA_CONFIG` evidence.

Answer synthesis must not infer external reachability from `DEPLOYS_VIA_CONFIG` alone.

## Alternatives Considered

### Widen `ROUTES_DOMAIN_TO_DEPLOY` to allow an absent domain

Rejected. A nullable domain would weaken a relation whose subject is intentionally a concrete `Domain`. It would also force every query and answer path to special-case route facts that are not actually routes.

### Add an Apache-specific `DEPLOYS_VIA_WSGI` predicate

Rejected as too narrow. WSGI is one source kind, not the domain concept. The relation should cover deploy-target proof from Apache/WSGI now and later support other config families such as systemd, Procfile, Docker, Kubernetes, or platform manifests.

### Defer domainless deploy proof indefinitely

Rejected. Product topology questions often need to know that a deploy target exists even when public routing evidence is missing. The correct response is not to hide the evidence; it is to expose the deploy proof with an explicit caveat.

## Consequences

Positive:

- Preserves strict route semantics.
- Gives product answers useful topology evidence without pretending a domain exists.
- Keeps the relation generic enough for multiple deploy/config systems.
- Makes future extractor tests straightforward: domainless WSGI should emit deploy-only evidence, not route evidence.

Negative:

- Adds one more predicate to the current fact vocabulary.
- Query and synthesis layers must merge route facts and deploy-only facts carefully.
- The current `DeployTarget` shape still needs future alignment with ADR-0006's canonical deployment ontology.

## Implementation Status

Decision only. No runtime behavior changes in this ADR.

When implemented, update:

- `source/kg/extraction/framework/allowlists.py` to allow `DEPLOYS_VIA_CONFIG`;
- Apache file-format adapter capability metadata to claim `DEPLOYS_VIA_CONFIG`;
- Apache extraction logic to emit deploy-only facts for domainless `WSGIScriptAlias`;
- tests that currently assert domainless WSGI emits no facts;
- query/retrieval surfaces that answer deploy-topology questions.

## Relationship to Existing ADRs

- ADR-0005 still owns coordinate-backed evidence retrieval. `DEPLOYS_VIA_CONFIG` facts must carry source coordinates suitable for Mode A fetch.
- ADR-0006 still owns the canonical ontology and fact envelope. This ADR defines a deploy-target evidence relation for local KG evaluation; future ontology work may map `DeployTarget` / `DEPLOYS_VIA_CONFIG` into canonical `Deployable` / `Deployment` terms.
- ADR-0004 still owns canonical-vs-candidate separation. Deterministic config facts covered by this ADR are canonical facts; candidate deploy facts must remain in explicit candidate/enrichment paths.
- ADR-0009 reverse dependency semantics are unchanged; deploy topology is not a reverse dependency query.

## References

- `source/kg/file_formats/apache_vhost.py`
- `source/kg/file_formats/adapters/config_apache_vhost.py`
- `source/kg/file_formats/_shared/deploy_events.py`
- `source/kg/extraction/framework/allowlists.py`
- `tests/test_apache_vhost_extraction.py`
