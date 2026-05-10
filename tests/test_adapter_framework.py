from __future__ import annotations

from dataclasses import dataclass
import tempfile
import unittest
from pathlib import Path

from source.kg.build.pipeline import extract_repo
from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.extraction.framework.registry import register
from source.kg.extraction.framework.runner import run_adapters


class AdapterFrameworkTest(unittest.TestCase):
    def test_registry_rejects_duplicate_capability_names(self) -> None:
        adapter = _Adapter("dup", "test_v0")

        with self.assertRaisesRegex(ValueError, "Duplicate adapter name: dup"):
            register((adapter, adapter))

    def test_runner_skips_adapter_when_applies_to_false(self) -> None:
        repo = _repo()
        adapter = _Adapter("skip", "skip_v0", applies=False)

        entities, facts, evidence, coverage, errors = run_adapters(repo, (adapter,))

        self.assertEqual((entities, facts, evidence, coverage, errors), ([], [], [], [], []))
        self.assertEqual(adapter.calls, 0)

    def test_runner_dedupes_facts_by_fact_id_and_merges_evidence(self) -> None:
        repo = _repo()
        service = _entity("Service", "svc")
        repo_entity = _entity("Repo", "repo")
        fact = Fact("DEFINED_IN", service.entity_id, repo_entity.entity_id)
        evidence_a = _evidence(fact, "a.py")
        evidence_b = _evidence(fact, "b.py")
        adapter_a = _Adapter(
            "a",
            "a_v0",
            result=AdapterResult(entities=[service, repo_entity], facts=[fact], evidence=[evidence_a]),
        )
        adapter_b = _Adapter("b", "b_v0", result=AdapterResult(entities=[], facts=[fact], evidence=[evidence_b]))

        _, facts, evidence, _, _ = run_adapters(repo, (adapter_a, adapter_b))

        self.assertEqual([row.fact_id for row in facts], [fact.fact_id])
        self.assertEqual({row.evidence_id for row in evidence}, {evidence_a.evidence_id, evidence_b.evidence_id})

    def test_runner_strict_mode_raises_aggregate_runtime_error_after_collecting_errors(self) -> None:
        repo = _repo()

        with self.assertRaisesRegex(RuntimeError, "one_v0: RuntimeError: first.*two_v0: ValueError: second"):
            run_adapters(
                repo,
                (
                    _Adapter("one", "one_v0", error=RuntimeError("first")),
                    _Adapter("two", "two_v0", error=ValueError("second")),
                ),
                strict_extractors=True,
            )

    def test_runner_non_strict_emits_uninstrumented_coverage_on_error(self) -> None:
        repo = _repo()

        _, _, _, coverage, errors = run_adapters(repo, (_Adapter("bad", "bad_v0", error=RuntimeError("boom")),))

        self.assertEqual(errors[0]["source_system"], "bad_v0")
        self.assertEqual(coverage[0].predicate, "PARSES")
        self.assertEqual(coverage[0].state, "uninstrumented")
        self.assertEqual(coverage[0].scope_ref["reason"], "adapter_error")
        self.assertEqual(coverage[0].source_system, "bad_v0")

    def test_runner_validation_rejects_unknown_predicate(self) -> None:
        repo = _repo()
        service = _entity("Service", "svc")
        repo_entity = _entity("Repo", "repo")
        bad_fact = Fact("MADE_UP", service.entity_id, repo_entity.entity_id)
        adapter = _Adapter(
            "bad-predicate",
            "bad_v0",
            result=AdapterResult(entities=[service, repo_entity], facts=[bad_fact]),
        )

        _, _, _, coverage, errors = run_adapters(repo, (adapter,))

        self.assertEqual(errors[0]["error"], "ValueError")
        self.assertIn("unsupported predicate", errors[0]["message"])
        self.assertEqual(coverage[0].scope_ref["reason"], "adapter_error")

    def test_runner_validation_requires_bytes_ref_for_source_file_systems(self) -> None:
        repo = _repo()
        entity = _entity("Service", "svc")
        evidence = Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="deterministic_static",
            source_system="python_ast_v0",
            source_ref={"path": "app.py"},
            bytes_ref=None,
        )
        adapter = _Adapter("bad-evidence", "bad_v0", result=AdapterResult(entities=[entity], evidence=[evidence]))

        _, _, _, _, errors = run_adapters(repo, (adapter,))

        self.assertIn("without bytes_ref", errors[0]["message"])

    def test_runner_language_gating_skips_python_adapter_without_python_files(self) -> None:
        repo = _repo(python_files=())
        adapter = _Adapter("python-only", "python_v0", languages=("python",))

        run_adapters(repo, (adapter,))

        self.assertEqual(adapter.calls, 0)

    def test_pipeline_reports_only_applicable_extractors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = RepoSnapshot(
                root=Path(tmpdir),
                name="config-only",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )

            build = extract_repo(repo)

        self.assertEqual(build.extractor_names, ["static_config_v0"])


@dataclass
class _Adapter:
    name: str
    source_system: str
    languages: tuple[str, ...] = ("config",)
    applies: bool = True
    result: AdapterResult | None = None
    error: Exception | None = None
    calls: int = 0

    @property
    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            name=self.name,
            languages=self.languages,
            produces_predicates=("DEFINED_IN",),
            produces_entity_kinds=("Service", "Repo"),
            source_system=self.source_system,
        )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return self.applies

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result or AdapterResult()


def _repo(python_files: tuple[Path, ...] | None = None, typescript_files: tuple[Path, ...] = ()) -> RepoSnapshot:
    root = Path("/tmp/bettercontext-adapter-framework-repo")
    return RepoSnapshot(
        root=root,
        name="repo",
        owner="test",
        commit_sha="sha",
        python_files=python_files if python_files is not None else (root / "app.py",),
        typescript_files=typescript_files,
    )


def _entity(kind: str, name: str) -> Entity:
    return Entity(kind=kind, identity={"tenant_id": "local-dev", "name": name})


def _evidence(fact: Fact, path: str) -> Evidence:
    return Evidence(
        target_type="fact",
        target_id=fact.fact_id,
        derivation_class="deterministic_static",
        source_system="test_static_v0",
        source_ref={"path": path},
        bytes_ref={"path": path, "line_start": 1, "line_end": 1, "commit_sha": "sha"},
    )
