from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.message_events import extract_typescript_message_events
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo


@dataclass(frozen=True)
class TypeScriptMessageTransportAdapter:
    capability = AdapterCapability(
        name="typescript-message-transport",
        languages=("javascript", "typescript"),
        file_kinds=("javascript", "typescript"),
        framework_tags=("@nestjs/microservices",),
        produces_predicates=("PRODUCES_EVENT", "CONSUMES_EVENT"),
        produces_entity_kinds=("EventChannel",),
        ontology_scope="mixed",
        source_system=StaticConfigExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("typescript", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = ConfigKgBuild()
        service_entity = StaticConfigExtractor()._service_entity(repo, ctx.tenant_id)
        parsed_files = parse_typescript_repo(repo, ctx)
        extract_typescript_message_events(repo, parsed_files, service_entity, build, ctx.tenant_id)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


TYPESCRIPT_MESSAGE_TRANSPORT_ADAPTER = TypeScriptMessageTransportAdapter()
