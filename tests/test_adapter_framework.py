from __future__ import annotations

import importlib
from dataclasses import dataclass
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.build.pipeline import extract_repo
from source.kg.core.models import Coverage, Entity, Evidence, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters import REGISTERED_ADAPTERS
from source.kg.extraction.adapters import config_shared
from source.kg.extraction.adapters.config_domain_env import CONFIG_DOMAIN_ENV_ADAPTER
from source.kg.extraction.adapters.config_serverless_yaml import CONFIG_SERVERLESS_YAML_ADAPTER
from source.kg.extraction.adapters.config_terraform import CONFIG_TERRAFORM_ADAPTER
from source.kg.extraction.adapters.config_zappa import CONFIG_ZAPPA_ADAPTER
from source.kg.extraction.adapters.legacy import LEGACY_STATIC_CONFIG_ADAPTER, LegacyAdapter
from source.kg.extraction.adapters.python_boto3_transport import PYTHON_BOTO3_TRANSPORT_ADAPTER
from source.kg.extraction.adapters.typescript_express_routes import TYPESCRIPT_EXPRESS_ROUTES_ADAPTER
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.extraction.framework.registry import register_for_tests, validate_adapters
from source.kg.extraction.framework.runner import run_adapters, select_applicable_adapters
from source.kg.extraction.python.ast_extractor import PythonAstExtractor


class AdapterFrameworkTest(unittest.TestCase):
    def test_registry_rejects_duplicate_capability_names(self) -> None:
        adapter = _Adapter("dup", "test_v0")

        with self.assertRaisesRegex(ValueError, "Duplicate adapter name: dup"):
            register_for_tests((adapter, adapter))

    def test_registry_rejects_missing_source_system(self) -> None:
        with self.assertRaisesRegex(ValueError, "must declare source_system"):
            register_for_tests((_Adapter("missing", ""),))

    def test_registry_rejects_unsupported_declared_predicate(self) -> None:
        adapter = _Adapter("bad-predicate-declaration", "test_v0", produces_predicates=("MADE_UP",))

        with self.assertRaisesRegex(ValueError, "declares unsupported predicates"):
            validate_adapters((adapter,))

    def test_registry_rejects_unsupported_declared_entity_kind(self) -> None:
        adapter = _Adapter("bad-kind-declaration", "test_v0", produces_entity_kinds=("MadeUp",))

        with self.assertRaisesRegex(ValueError, "declares unsupported entity kinds"):
            validate_adapters((adapter,))

    def test_runner_non_strict_converts_missing_source_system_to_error_coverage(self) -> None:
        repo = _repo()

        _, _, _, coverage, errors = run_adapters(repo, (_Adapter("missing", ""),))

        self.assertEqual(errors[0]["source_system"], "extraction_framework")
        self.assertIn("must declare source_system", errors[0]["message"])
        self.assertEqual(coverage[0].source_system, "extraction_framework")
        self.assertEqual(coverage[0].scope_ref["adapter"], "missing")

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

    def test_runner_dedupes_coverage_by_coverage_id(self) -> None:
        repo = _repo()
        row = Coverage(
            tenant_id="local-dev",
            predicate="CONFIG_SCAN",
            scope_ref={"repo": "repo", "file_path": ".env", "reason": "exceeds_max_scan_bytes"},
            state="uninstrumented",
            source_system="static_config_v0",
        )
        adapter_a = _Adapter("a", "a_v0", result=AdapterResult(coverage=[row]))
        adapter_b = _Adapter("b", "b_v0", result=AdapterResult(coverage=[row]))

        _, _, _, coverage, _ = run_adapters(repo, (adapter_a, adapter_b))

        self.assertEqual([coverage_row.coverage_id for coverage_row in coverage], [row.coverage_id])

    def test_runner_does_not_dedupe_adapter_error_coverage(self) -> None:
        repo = _repo()

        _, _, _, coverage, errors = run_adapters(
            repo,
            (
                _Adapter("same", "same_v0", error=RuntimeError("boom")),
                _Adapter("same", "same_v0", error=RuntimeError("boom")),
            ),
        )

        self.assertEqual(len(errors), 2)
        self.assertEqual(len([row for row in coverage if row.scope_ref.get("reason") == "adapter_error"]), 2)

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

    def test_runner_strict_validation_rejects_unknown_predicate(self) -> None:
        repo = _repo()
        service = _entity("Service", "svc")
        repo_entity = _entity("Repo", "repo")
        bad_fact = Fact("MADE_UP", service.entity_id, repo_entity.entity_id)
        adapter = _Adapter(
            "bad-predicate",
            "bad_v0",
            result=AdapterResult(entities=[service, repo_entity], facts=[bad_fact]),
        )

        with self.assertRaisesRegex(RuntimeError, "unsupported predicate"):
            run_adapters(repo, (adapter,), strict_extractors=True)

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

    def test_selection_reads_capability_once_per_adapter(self) -> None:
        repo = _repo()
        adapter = _Adapter("stateful-capability", "stateful_v0")

        selected = select_applicable_adapters(repo, (adapter,))

        self.assertEqual(selected, [adapter])
        self.assertEqual(adapter.capability_reads, 1)

    def test_registry_validation_reads_capability_once_per_adapter(self) -> None:
        adapter = _Adapter("stateful-capability", "stateful_v0")

        validate_adapters((adapter,))

        self.assertEqual(adapter.capability_reads, 1)

    def test_pipeline_selection_does_not_call_applies_to_twice(self) -> None:
        repo = _repo()
        adapter = _Adapter("stateful", "stateful_v0")

        selected = run_adapters(repo, (adapter,))

        self.assertEqual(adapter.applies_calls, 1)
        self.assertEqual(selected, ([], [], [], [], []))

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

    def test_pipeline_reuses_selection_capability_for_extractor_names(self) -> None:
        repo = _repo()
        adapter = _Adapter("stateful", "stateful_v0")

        with (
            patch("source.kg.extraction.adapters.REGISTERED_ADAPTERS", (adapter,)),
            patch("source.kg.languages.language_adapters", return_value=()),
        ):
            build = extract_repo(repo)

        self.assertEqual(build.extractor_names, ["stateful_v0"])
        self.assertEqual(adapter.capability_reads, 3)

    def test_extraction_context_lazy_properties_do_not_change_equality(self) -> None:
        left = ExtractionContext()
        right = ExtractionContext()

        self.assertFalse(left == right)
        _ = left.python_parsed_files
        _ = left.js_ts_import_roots

        self.assertFalse(left == right)

    def test_extraction_context_repr_excludes_large_mutable_caches(self) -> None:
        ctx = ExtractionContext(
            tenant_id="tenant",
            config_scans={"large": "scan"},
            parsed_by_language={"python": {"repo": "parsed"}},
            literal_indexes_by_language={"python": {"repo": "literal"}},
            import_roots_by_language={"python": {"flask"}},
        )

        rendered = repr(ctx)

        self.assertEqual(rendered, "ExtractionContext(tenant_id='tenant')")
        self.assertNotIn("parsed", rendered)
        self.assertNotIn("flask", rendered)

    def test_repo_snapshot_hash_and_equality_use_stable_identity(self) -> None:
        root = Path("/tmp/bettercontext-adapter-framework-repo")
        left = RepoSnapshot(
            root=root,
            name="repo",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (root / "app.py",)},
        )
        right = RepoSnapshot(
            root=root,
            name="repo",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (), "typescript": (root / "app.ts",)},
        )

        self.assertEqual(left, right)
        self.assertEqual(hash(left), hash(right))

    def test_repo_snapshot_files_by_language_is_read_only(self) -> None:
        root = Path("/tmp/bettercontext-adapter-framework-repo")
        repo = RepoSnapshot(
            root=root,
            name="repo",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (root / "app.py",)},
        )

        with self.assertRaises(TypeError):
            repo.files_by_language["python"] = ()

    def test_repo_snapshot_rejects_mixed_generic_and_legacy_file_args(self) -> None:
        root = Path("/tmp/bettercontext-adapter-framework-repo")

        with self.assertRaisesRegex(ValueError, "Pass either files_by_language or legacy"):
            RepoSnapshot(
                root=root,
                name="repo",
                owner="test",
                commit_sha="sha",
                files_by_language={"python": ()},
                python_files=(root / "app.py",),
            )

    def test_pipeline_selects_language_discovered_adapters_without_central_registry(self) -> None:
        repo = _repo()
        adapter = _Adapter("language-owned", "language_owned_v0", languages=("python",))

        with (
            patch("source.kg.extraction.adapters.REGISTERED_ADAPTERS", ()),
            patch("source.kg.languages.language_adapters", return_value=(adapter,)),
        ):
            build = extract_repo(repo)

        self.assertEqual(build.extractor_names, ["language_owned_v0"])
        self.assertEqual(adapter.calls, 1)

    def test_registered_adapters_include_pr_fw_2_splits(self) -> None:
        names = {adapter.capability.name for adapter in REGISTERED_ADAPTERS}

        self.assertIn("python-boto3-transport", names)
        self.assertIn("config-apache-vhost", names)
        self.assertIn("config-domain-env", names)
        self.assertIn("config-openapi", names)
        self.assertIn("config-terraform", names)
        self.assertIn("config-zappa", names)
        self.assertIn("config-serverless-yaml", names)

    def test_split_config_capabilities_include_yml_file_kind(self) -> None:
        capabilities = {adapter.capability.name: adapter.capability for adapter in REGISTERED_ADAPTERS}

        self.assertIn("yml", capabilities["config-openapi"].file_kinds)
        self.assertIn("yml", capabilities["config-serverless-yaml"].file_kinds)

    def test_domain_env_adapter_uses_config_language_bucket(self) -> None:
        repo = _repo(python_files=(), typescript_files=())
        capabilities = {adapter.capability.name: adapter.capability for adapter in REGISTERED_ADAPTERS}

        selected = select_applicable_adapters(repo, (CONFIG_DOMAIN_ENV_ADAPTER,))

        self.assertEqual(selected, [CONFIG_DOMAIN_ENV_ADAPTER])
        self.assertEqual(CONFIG_DOMAIN_ENV_ADAPTER.capability.languages, ("config",))
        self.assertEqual(CONFIG_DOMAIN_ENV_ADAPTER.capability.file_kinds, ("config",))
        for name in (
            "config-apache-vhost",
            "config-domain-env",
            "config-dotenv",
            "config-openapi",
            "config-serverless-yaml",
            "config-terraform",
            "config-zappa",
            "event-channel-normalizer",
        ):
            self.assertEqual(capabilities[name].languages, ("config",))

    def test_file_format_modules_are_canonical_with_compatibility_aliases(self) -> None:
        legacy_to_canonical = {
            "source.kg.extraction.config.apache_vhost": "source.kg.extraction.file_formats.apache_vhost",
            "source.kg.extraction.config.channel_normalization": "source.kg.extraction.file_formats.channel_normalization",
            "source.kg.extraction.config.common": "source.kg.extraction.file_formats.common",
            "source.kg.extraction.config.deploy_events": "source.kg.extraction.file_formats.deploy_events",
            "source.kg.extraction.config.domain_env": "source.kg.extraction.file_formats.domain_env",
            "source.kg.extraction.config.domain_literals": "source.kg.extraction.file_formats.domain_literals",
            "source.kg.extraction.config.dotenv": "source.kg.extraction.file_formats.dotenv",
            "source.kg.extraction.config.endpoints": "source.kg.extraction.file_formats.endpoints",
            "source.kg.extraction.config.openapi_yaml": "source.kg.extraction.file_formats.openapi_yaml",
            "source.kg.extraction.config.serverless_yaml": "source.kg.extraction.file_formats.serverless_yaml",
            "source.kg.extraction.config.static_extractor": "source.kg.extraction.file_formats.static_extractor",
            "source.kg.extraction.config.terraform": "source.kg.extraction.file_formats.terraform",
            "source.kg.extraction.config.zappa": "source.kg.extraction.file_formats.zappa",
            "source.kg.extraction.adapters.config_apache_vhost": (
                "source.kg.extraction.file_formats.adapters.config_apache_vhost"
            ),
            "source.kg.extraction.adapters.config_domain_env": (
                "source.kg.extraction.file_formats.adapters.config_domain_env"
            ),
            "source.kg.extraction.adapters.config_dotenv": "source.kg.extraction.file_formats.adapters.config_dotenv",
            "source.kg.extraction.adapters.config_openapi": "source.kg.extraction.file_formats.adapters.config_openapi",
            "source.kg.extraction.adapters.config_serverless_yaml": (
                "source.kg.extraction.file_formats.adapters.config_serverless_yaml"
            ),
            "source.kg.extraction.adapters.config_shared": "source.kg.extraction.file_formats.adapters.config_shared",
            "source.kg.extraction.adapters.config_terraform": (
                "source.kg.extraction.file_formats.adapters.config_terraform"
            ),
            "source.kg.extraction.adapters.config_zappa": "source.kg.extraction.file_formats.adapters.config_zappa",
            "source.kg.extraction.adapters.event_channel_normalizer": (
                "source.kg.extraction.file_formats.adapters.event_channel_normalizer"
            ),
        }

        for legacy_name, canonical_name in legacy_to_canonical.items():
            with self.subTest(legacy=legacy_name):
                self.assertIs(importlib.import_module(legacy_name), importlib.import_module(canonical_name))
        self.assertEqual(CONFIG_DOMAIN_ENV_ADAPTER.__class__.__module__, "source.kg.extraction.file_formats.adapters.config_domain_env")
        self.assertIs(
            importlib.import_module("source.kg.extraction.file_formats.adapters.config_openapi").CONFIG_OPENAPI_ADAPTER,
            {adapter.capability.name: adapter for adapter in REGISTERED_ADAPTERS}["config-openapi"],
        )

    def test_zappa_adapter_claims_parser_backed_public_scope(self) -> None:
        capability = CONFIG_ZAPPA_ADAPTER.capability

        self.assertIn("zappa", capability.framework_tags)
        self.assertIn("CONSUMES_EVENT", capability.produces_predicates)
        self.assertIn("EventChannel", capability.produces_entity_kinds)

    def test_terraform_adapter_claims_parser_backed_public_scope(self) -> None:
        capability = CONFIG_TERRAFORM_ADAPTER.capability

        self.assertIn("terraform", capability.framework_tags)
        self.assertIn("REFERENCES_DOMAIN", capability.produces_predicates)
        self.assertIn("Domain", capability.produces_entity_kinds)

    def test_apache_vhost_adapter_claims_parser_backed_public_scope(self) -> None:
        capability = {adapter.capability.name: adapter.capability for adapter in REGISTERED_ADAPTERS}["config-apache-vhost"]

        self.assertIn("apache", capability.framework_tags)
        self.assertIn("wsgi", capability.framework_tags)
        self.assertIn("REFERENCES_DOMAIN", capability.produces_predicates)
        self.assertIn("ROUTES_DOMAIN_TO_DEPLOY", capability.produces_predicates)
        self.assertIn("Domain", capability.produces_entity_kinds)
        self.assertIn("DeployTarget", capability.produces_entity_kinds)

    def test_serverless_yaml_adapter_claims_parser_backed_public_scope(self) -> None:
        capability = CONFIG_SERVERLESS_YAML_ADAPTER.capability

        self.assertIn("serverless", capability.framework_tags)
        self.assertIn("EXPOSES_ENDPOINT", capability.produces_predicates)
        self.assertIn("CONSUMES_EVENT", capability.produces_predicates)
        self.assertIn("Endpoint", capability.produces_entity_kinds)
        self.assertIn("EventChannel", capability.produces_entity_kinds)

    def test_typescript_route_adapter_claims_supported_web_frameworks(self) -> None:
        capability = TYPESCRIPT_EXPRESS_ROUTES_ADAPTER.capability

        self.assertIn("express", capability.framework_tags)
        self.assertIn("fastify", capability.framework_tags)
        self.assertIn("koa", capability.framework_tags)
        self.assertIn("EXPOSES_ENDPOINT", capability.produces_predicates)
        self.assertIn("Endpoint", capability.produces_entity_kinds)

    def test_config_split_pipeline_matches_static_config_monolith(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text('API_URL="https://api.example.com"\n', encoding="utf-8")
            (root / "openapi.yaml").write_text(
                "openapi: 3.0.0\npaths:\n  /orders:\n    get:\n      responses: {}\n",
                encoding="utf-8",
            )
            (root / "serverless.yml").write_text(
                "functions:\n  ws:\n    handler: app.handler\n    events:\n      - websocket:\n          route: $connect\n",
                encoding="utf-8",
            )
            (root / "zappa_settings.json").write_text(
                '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "'
                'arn:aws:sqs:eu-west-1:123456789012:orders-created"}}]}}',
                encoding="utf-8",
            )
            (root / "main.tf").write_text(
                'variable "api_domain" {\n'
                '  default = "terraform.example.com"\n'
                "}\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="config-split",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )

            monolith = StaticConfigExtractor().extract(repo)
            split = extract_repo(repo)

        self.assertEqual(_entity_ids(split.entities), _entity_ids(monolith.entities))
        self.assertEqual(_fact_ids(split.facts), _fact_ids(monolith.facts))
        self.assertEqual(_evidence_ids(split.evidence), _evidence_ids(monolith.evidence))
        self.assertEqual(_coverage_ids(split.coverage), _coverage_ids(monolith.coverage))

    def test_config_split_adapters_share_one_config_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text('API_URL="https://api.example.com"\n', encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="config-scan",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )

            with patch(
                "source.kg.extraction.adapters.config_shared.scan_config_files",
                wraps=config_shared.scan_config_files,
            ) as scan:
                extract_repo(repo)

        self.assertEqual(scan.call_count, 1)

    def test_large_config_file_skip_emits_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_URL=https://api.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="large-config",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )

            with patch("source.kg.extraction.config.common.MAX_SCAN_BYTES", 4):
                build = extract_repo(repo)

        rows = {
            row.coverage_id: row
            for row in build.coverage
            if row.predicate == "CONFIG_SCAN" and row.scope_ref.get("reason") == "exceeds_max_scan_bytes"
        }
        self.assertEqual(len(rows), 1)
        row = next(iter(rows.values()))
        self.assertEqual(row.state, "uninstrumented")
        self.assertEqual(row.source_system, "static_config_v0")
        self.assertEqual(row.scope_ref["repo"], "large-config")
        self.assertEqual(row.scope_ref["file_path"], ".env")
        self.assertEqual(row.scope_ref["max_scan_bytes"], 4)

    def test_split_config_adapters_dedupe_shared_scan_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("API_URL=https://api.example.com\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="config-dedupe",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )

            with patch("source.kg.extraction.config.common.MAX_SCAN_BYTES", 4):
                _, _, _, coverage, _ = run_adapters(repo, (LEGACY_STATIC_CONFIG_ADAPTER, CONFIG_DOMAIN_ENV_ADAPTER))

        rows = [row for row in coverage if row.scope_ref.get("reason") == "exceeds_max_scan_bytes"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].scope_ref["file_path"], ".env")

    def test_python_transport_split_matches_python_ast_monolith(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text(
                "import boto3\n\n"
                "def publish_order():\n"
                "    client = boto3.client('sqs')\n"
                "    client.send_message(QueueUrl='https://sqs.us-east-1.amazonaws.com/123/orders', MessageBody='x')\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="python-split",
                owner="test",
                commit_sha="sha",
                python_files=(app,),
                typescript_files=(),
            )

            monolith = PythonAstExtractor().extract(repo)
            reduced = PythonAstExtractor(include_transport=False).extract(repo)
            split = PYTHON_BOTO3_TRANSPORT_ADAPTER.extract(repo, ExtractionContext())

        self.assertEqual(_entity_ids(reduced.entities + split.entities), _entity_ids(monolith.entities))
        self.assertEqual(_fact_ids(reduced.facts + split.facts), _fact_ids(monolith.facts))
        self.assertEqual(_evidence_ids(reduced.evidence + split.evidence), _evidence_ids(monolith.evidence))
        self.assertEqual(_coverage_ids(reduced.coverage + split.coverage), _coverage_ids(monolith.coverage))

    def test_python_split_adapters_share_parsed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text(
                "import boto3\n\n"
                "def publish_order():\n"
                "    client = boto3.client('sqs')\n"
                "    client.send_message(QueueUrl='https://sqs.us-east-1.amazonaws.com/123/orders', MessageBody='x')\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="python-cache",
                owner="test",
                commit_sha="sha",
                python_files=(app,),
                typescript_files=(),
            )
            original_parse_file = PythonAstExtractor._parse_file
            parsed_paths: list[Path] = []

            def counted_parse_file(extractor: PythonAstExtractor, file_path: Path):
                parsed_paths.append(file_path)
                return original_parse_file(extractor, file_path)

            with patch.object(PythonAstExtractor, "_parse_file", counted_parse_file):
                extract_repo(repo)

        self.assertEqual(parsed_paths, [app])

    def test_known_stack_without_adapter_tag_emits_uninstrumented_coverage(self) -> None:
        repo = _repo(python_files=())
        adapter = _ImportRootAdapter("js-imports", "js_imports_v0", js_ts_import_roots=("express",))

        _, _, _, coverage, errors = run_adapters(repo, (adapter,))

        self.assertEqual(errors, [])
        rows = _known_stack_rows(coverage)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.predicate, "EXPOSES_ENDPOINT")
        self.assertEqual(row.state, "uninstrumented")
        self.assertEqual(row.source_system, "extraction_framework")
        self.assertEqual(row.scope_ref["language"], "javascript")
        self.assertEqual(row.scope_ref["import_root"], "express")
        self.assertEqual(row.scope_ref["reason"], "no_adapter_for_known_stack")

    def test_known_stack_with_adapter_tag_does_not_emit_refusal_coverage(self) -> None:
        repo = _repo(python_files=())
        adapter = _ImportRootAdapter(
            "express-routes",
            "express_routes_v0",
            js_ts_import_roots=("express",),
            framework_tags=("express",),
        )

        _, _, _, coverage, _ = run_adapters(repo, (adapter,))

        self.assertEqual([row for row in coverage if row.scope_ref.get("reason") == "no_adapter_for_known_stack"], [])

    def test_python_extractor_populates_import_roots_for_known_stack_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text("import flask\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="python-known-stack",
                owner="test",
                commit_sha="sha",
                python_files=(app,),
                typescript_files=(),
            )
            adapter = LegacyAdapter(
                capability=AdapterCapability(
                    name="python-import-root-test",
                    languages=("python",),
                    produces_predicates=("DEFINED_IN", "IMPLEMENTS", "IMPORTS", "CALLS"),
                    produces_entity_kinds=("Repo", "Service", "CodeModule", "ExternalPackage"),
                    ontology_scope="mixed",
                    source_system=PythonAstExtractor.source_system,
                ),
                extractor=PythonAstExtractor(include_transport=False),
                language_gate="python",
            )

            _, _, _, coverage, errors = run_adapters(repo, (adapter,))

        self.assertEqual(errors, [])
        rows = _known_stack_rows(coverage)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].predicate, "EXPOSES_ENDPOINT")
        self.assertEqual(rows[0].scope_ref["language"], "python")
        self.assertEqual(rows[0].scope_ref["import_root"], "flask")

    def test_unknown_known_stack_category_fails_closed(self) -> None:
        repo = _repo(python_files=())

        with patch("source.kg.extraction.framework.runner._registered_languages", return_value=(_UnknownCategoryLanguage(),)):
            _, _, _, coverage, errors = run_adapters(repo, ())

        self.assertEqual(errors, [])
        self.assertEqual(_known_stack_rows(coverage), [])


@dataclass
class _Adapter:
    name: str
    source_system: str
    languages: tuple[str, ...] = ("config",)
    applies: bool = True
    produces_predicates: tuple[str, ...] = ("DEFINED_IN",)
    produces_entity_kinds: tuple[str, ...] = ("Service", "Repo")
    framework_tags: tuple[str, ...] = ()
    result: AdapterResult | None = None
    error: Exception | None = None
    calls: int = 0
    applies_calls: int = 0
    capability_reads: int = 0

    @property
    def capability(self) -> AdapterCapability:
        self.capability_reads += 1
        return AdapterCapability(
            name=self.name,
            languages=self.languages,
            framework_tags=self.framework_tags,
            produces_predicates=self.produces_predicates,
            produces_entity_kinds=self.produces_entity_kinds,
            source_system=self.source_system,
        )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        self.applies_calls += 1
        return self.applies

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result or AdapterResult()


@dataclass
class _ImportRootAdapter(_Adapter):
    python_import_roots: tuple[str, ...] = ()
    js_ts_import_roots: tuple[str, ...] = ()

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        self.calls += 1
        ctx.python_import_roots.update(self.python_import_roots)
        ctx.js_ts_import_roots.update(self.js_ts_import_roots)
        return self.result or AdapterResult()


class _UnknownCategoryLanguage:
    name = "python"
    aliases: tuple[str, ...] = ()

    def source_roots(self, repo: RepoSnapshot, ctx: ExtractionContext) -> dict[str, set[str]]:
        return {"python": {"custom_stack"}}

    def known_stacks(self) -> dict[str, dict[str, str]]:
        return {"python": {"custom_stack": "unknown_category"}}


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


def _entity_ids(entities: list[Entity]) -> set[str]:
    return {entity.entity_id for entity in entities}


def _fact_ids(facts: list[Fact]) -> set[str]:
    return {fact.fact_id for fact in facts}


def _evidence_ids(evidence: list[Evidence]) -> set[str]:
    return {row.evidence_id for row in evidence}


def _coverage_ids(coverage: list) -> set[str]:
    return {row.coverage_id for row in coverage}


def _known_stack_rows(coverage: list):
    return [row for row in coverage if row.scope_ref.get("reason") == "no_adapter_for_known_stack"]
