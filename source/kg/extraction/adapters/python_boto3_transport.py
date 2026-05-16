from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.python.extractors.ast_extractor import PythonAstExtractor


@dataclass(frozen=True)
class PythonBoto3TransportAdapter:
    capability = AdapterCapability(
        name="python-boto3-transport",
        languages=("python",),
        file_kinds=("python",),
        framework_tags=("boto3", "sqs", "sns"),
        produces_predicates=("PRODUCES_EVENT", "CONSUMES_EVENT"),
        produces_entity_kinds=("EventChannel",),
        ontology_scope="mixed",
        source_system=PythonAstExtractor.source_system,
    )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.python_files)

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = PythonAstExtractor(include_transport=False).extract_transport_events_only(repo, ctx)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


PYTHON_BOTO3_TRANSPORT_ADAPTER = PythonBoto3TransportAdapter()
