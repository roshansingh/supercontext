from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.languages.python.extractors.ast_extractor import PythonAstExtractor


@dataclass(frozen=True)
class ExtractorAdapter:
    capability: AdapterCapability
    extractor: PythonAstExtractor

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return bool(repo.files_by_language.get("python", ()))

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        build = self.extractor.extract_with_context(repo, ctx)
        return AdapterResult(
            entities=list(build.entities),
            facts=list(build.facts),
            support_facts=list(build.support_facts),
            evidence=list(build.evidence),
            coverage=list(build.coverage),
        )


PYTHON_AST_ADAPTER = ExtractorAdapter(
    capability=AdapterCapability(
        name="python-ast",
        languages=("python",),
        file_kinds=("python",),
        framework_tags=("flask", "django", "fastapi"),
        produces_predicates=(
            "DEFINED_IN",
            "IMPLEMENTS",
            "IMPORTS",
            "CALLS",
            "EXPOSES_ENDPOINT",
        ),
        produces_support_predicates=(
            "DECLARES_FIELD",
            "RELATES_TO_MODEL",
            "SERIALIZES_MODEL",
            "HANDLES_MODEL",
            "TASK_USES_MODEL",
        ),
        produces_entity_kinds=(
            "Repo",
            "Service",
            "CodeModule",
            "CodeSymbol",
            "ExternalPackage",
            "ExternalSymbol",
            "Endpoint",
        ),
        ontology_scope="mixed",
        source_system=PythonAstExtractor.source_system,
    ),
    extractor=PythonAstExtractor(include_transport=False),
)
