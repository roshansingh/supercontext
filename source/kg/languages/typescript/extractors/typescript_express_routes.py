from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.endpoints import (
    extract_typescript_client_endpoint_calls,
    extract_typescript_express_routes,
)
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo


@dataclass(frozen=True)
class TypeScriptExpressRoutesAdapter:
    capability = AdapterCapability(
        name="typescript-express-routes",
        languages=("javascript", "typescript"),
        file_kinds=("javascript", "typescript"),
        framework_tags=("express", "fastify", "koa", "@koa/router", "koa-router"),
        produces_predicates=("EXPOSES_ENDPOINT", "CALLS_ENDPOINT"),
        produces_entity_kinds=("Endpoint",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("typescript", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        parsed_files = parse_typescript_repo(repo, ctx)
        extract_typescript_express_routes(repo, parsed_files, service_entity, build, ctx.tenant_id)
        extract_typescript_client_endpoint_calls(repo, parsed_files, service_entity, build, ctx.tenant_id)
        # This adapter does not consume config-scan files; scan coverage is
        # surfaced by the config adapters that use scannable_config_files().
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


TYPESCRIPT_EXPRESS_ROUTES_ADAPTER = TypeScriptExpressRoutesAdapter()
