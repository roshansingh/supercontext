from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile
from source.kg.extraction.config.terraform import extract_terraform


class TerraformExtractionTest(unittest.TestCase):
    def test_variable_default_domain_emits_reference(self) -> None:
        build = _extract(
            'variable "api_domain" {\n'
            '  default = "api.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)

    def test_resource_attribute_url_emits_reference(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {\n'
            '  name = "https://API.EXAMPLE.com:8443/v1"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])
        fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN")
        self.assertEqual(fact.qualifier["source_kind"], "terraform_literal")
        self.assertEqual(fact.qualifier["literal"], "https://api.example.com:8443/v1")

    def test_interpolation_is_skipped(self) -> None:
        build = _extract(
            'variable "api_domain" {\n'
            '  default = "${var.domain}"\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_scalar_with_trailing_tokens_is_skipped(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            '  default = "api.example.com" "cdn.example.com"\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_empty_scalar_emits_nothing(self) -> None:
        build = _extract(
            'variable "domain" {\n'
            '  default = ""\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_list_literal_emits_each_domain(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            '  default = ["api.example.com", "cdn.example.com"]\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["api.example.com", "cdn.example.com"])
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 2)

    def test_empty_list_emits_nothing(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            "  default = []\n"
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_list_with_unquoted_value_is_skipped(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            '  default = ["api.example.com", var.other]\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_malformed_list_is_skipped(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            '  default = ["api.example.com",, "cdn.example.com"]\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_list_with_trailing_comma_is_skipped(self) -> None:
        build = _extract(
            'variable "domains" {\n'
            '  default = ["api.example.com",]\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_single_quoted_value_is_skipped(self) -> None:
        build = _extract(
            'variable "api_domain" {\n'
            "  default = 'api.example.com'\n"
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_commented_line_is_skipped(self) -> None:
        build = _extract(
            'variable "api_domain" {\n'
            '  # default = "api.example.com"\n'
            '  default = "active.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["active.example.com"])

    def test_escaped_quote_does_not_start_comment_or_close_block(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {\n'
            '  note = "escaped \\" # { text"\n'
            '  name = "api.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["api.example.com"])

    def test_non_domain_literal_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_s3_bucket" "bucket" {\n'
            '  bucket = "not-a-domain"\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_module_source_https_emits_domain(self) -> None:
        build = _extract(
            'module "api" {\n'
            '  source = "git::https://github.com/example/api-module.git"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["github.com"])
        fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN")
        self.assertEqual(fact.qualifier["source_kind"], "terraform_module_source")
        self.assertEqual(fact.qualifier["literal"], "github.com")

    def test_module_source_ssh_emits_domain(self) -> None:
        build = _extract(
            'module "api" {\n'
            '  source = "git@github.com:example/api-module.git"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["github.com"])
        fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_DOMAIN")
        self.assertEqual(fact.qualifier["source_kind"], "terraform_module_source")

    def test_module_block_without_source_skips(self) -> None:
        build = _extract(
            'module "api" {\n'
            '  domain = "api.example.com"\n'
            "}\n"
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_nested_block_assignment_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_cloudfront_distribution" "api" {\n'
            "  origin {\n"
            '    domain_name = "api.example.com"\n'
            "  }\n"
            '  comment = "root.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["root.example.com"])

    def test_inline_nested_block_assignment_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_cloudfront_distribution" "api" {\n'
            '  origin { domain_name = "api.example.com" }\n'
            '  comment = "root.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["root.example.com"])

    def test_single_line_closed_block_does_not_leak_context(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {}\n'
            'name = "api.example.com"\n'
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])

    def test_block_comment_domain_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {\n'
            "  /*\n"
            '  name = "commented.example.com"\n'
            "  */\n"
            '  name = "active.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["active.example.com"])

    def test_inline_block_comment_domain_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {\n'
            '  /* name = "commented.example.com" */\n'
            '  name = "active.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["active.example.com"])

    def test_heredoc_body_assignment_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_instance" "api" {\n'
            "  user_data = <<EOF\n"
            '  export API_URL="heredoc.example.com"\n'
            '  name = "also-heredoc.example.com"\n'
            "  EOF\n"
            '  name = "active.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["active.example.com"])

    def test_heredoc_body_comment_tokens_do_not_affect_parser_state(self) -> None:
        build = _extract(
            'resource "aws_instance" "api" {\n'
            "  user_data = <<-EOF\n"
            "  /* shell comment token, not HCL comment\n"
            '  name = "heredoc.example.com"\n'
            "  EOF\n"
            '  name = "active.example.com"\n'
            "}\n"
        )

        self.assertEqual(_domains(build), ["active.example.com"])

    def test_non_tf_file_is_skipped(self) -> None:
        build = _extract(
            'resource "aws_route53_record" "api" {\n'
            '  name = "api.example.com"\n'
            "}\n",
            relative_path="main.txt",
        )

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])


def _extract(text: str, *, relative_path: str = "main.tf") -> ConfigKgBuild:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        terraform_path = root / relative_path
        terraform_path.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(root=root, name="terraform-service", owner="test", commit_sha="sha", python_files=(), typescript_files=())
        scanned = ScannedFile(
            path=terraform_path,
            relative_path=relative_path,
            text=text,
            lines=tuple(text.splitlines()),
        )
        service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
        build = ConfigKgBuild()
        extract_terraform(repo, scanned, service, build, "default")
        return build


def _domains(build: ConfigKgBuild) -> list[str]:
    return [entity.identity["name"] for entity in build.entities if entity.kind == "Domain"]


def _fact_count(build: ConfigKgBuild, predicate: str) -> int:
    return len([fact for fact in build.facts if fact.predicate == predicate])


if __name__ == "__main__":
    unittest.main()
