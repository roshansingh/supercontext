# Java, .NET, and Terraform Taxonomy Note

Status: temporary planning note

This note captures the current recommendation for adding Java, .NET, and Terraform support without prematurely changing the canonical ontology.

## Recommendation

Mostly no ontology change is needed for Java and .NET. They are new source languages, not new product concepts.

They should still emit the same KG concepts:

```text
Repo
Service
CodeSymbol / CodeModule in v0
Endpoint
Schema
EventChannel
Deployable
Deployment
Environment
IMPORTS / CALLS / EXPOSES_ENDPOINT / CALLS_ENDPOINT / PRODUCES_EVENT / CONSUMES_EVENT
```

What changes is the extractor taxonomy, not the ontology:

- Java frameworks: Spring MVC/WebFlux, JAX-RS, Micronaut, Quarkus
- Java build/package systems: Maven, Gradle
- .NET frameworks: ASP.NET controllers/minimal APIs, hosted workers
- .NET package system: NuGet
- Language-specific symbol identity: package/namespace/class/method, assembly/project, etc.

## Terraform

Terraform is slightly different. It still should not force a big ontology change if we keep the product wedge tight. Most Terraform resources can map into existing concepts:

```text
aws_route53_record -> Domain
aws_sqs_queue / aws_sns_topic -> EventChannel
aws_api_gateway_* -> Endpoint / API surface
kubernetes_deployment / aws_ecs_service / aws_lambda_function -> Deployable
workspace/env/provider/account/region -> Environment-ish qualifier or Environment
```

Terraform probably needs a resource mapping taxonomy:

```text
provider.resource_type -> KG entity/fact mapping
```

Examples:

```text
aws_sqs_queue -> EventChannel, REFERENCES_EVENT_CHANNEL
aws_route53_record -> Domain, REFERENCES_DOMAIN
kubernetes_deployment -> Deployable, RUNS_SERVICE if service identity is known
```

For unknown Terraform resources, emit coverage, not junk facts.

## Near-Term Rules

1. Do not change the canonical ontology yet.
2. Add a clear source/extractor taxonomy:
   - language
   - framework
   - package manager
   - config/IaC provider
   - source kind
   - emitted predicates
   - supported opportunity types
3. For Terraform, add a provider resource mapping table.
4. Only change ontology if we hit a product concept that cannot fit existing nodes/relations.

The likely future ontology pressure is not Java or .NET. It is Terraform if we decide to model arbitrary infrastructure inventory like databases, buckets, caches, IAM roles, secrets, feature flags, etc. Those are currently outside the Product 1 ontology. For now, map only product-relevant infrastructure into existing `Domain`, `Endpoint`, `EventChannel`, `Deployable`, `Deployment`, and `Environment`.

