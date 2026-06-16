from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ConfigKgBuild, ScannedFile
from source.kg.file_formats.terraform import extract_terraform, extract_terraform_files


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

    def test_lambda_event_source_mapping_emits_sqs_and_stream_consumers(self) -> None:
        build = _extract_files(
            {
                "events.tf": (
                    'resource "aws_sqs_queue" "orders" {\n'
                    '  name = "orders-created"\n'
                    "}\n"
                    'resource "aws_lambda_event_source_mapping" "orders" {\n'
                    "  event_source_arn = aws_sqs_queue.orders.arn\n"
                    '  function_name = "orders-worker"\n'
                    "}\n"
                    'resource "aws_lambda_event_source_mapping" "stream" {\n'
                    '  event_source_arn = "arn:aws:kinesis:us-east-1:123456789012:stream/orders-stream"\n'
                    '  function_name = "stream-worker"\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(
            _event_channels(build),
            [("kinesis", "orders-stream"), ("sqs", "orders-created")],
        )
        self.assertEqual(_event_source_kinds(build), ["terraform_lambda_event_source_mapping"])
        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 2)

    def test_sns_topic_subscription_emits_topic_consumer(self) -> None:
        build = _extract_files(
            {
                "events.tf": (
                    'resource "aws_sns_topic" "orders" {\n'
                    '  name = "orders-topic"\n'
                    "}\n"
                    'resource "aws_sns_topic_subscription" "orders" {\n'
                    "  topic_arn = aws_sns_topic.orders.arn\n"
                    '  protocol = "lambda"\n'
                    '  endpoint = "arn:aws:lambda:us-east-1:123456789012:function:orders-worker"\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_event_channels(build), [("sns", "orders-topic")])
        self.assertEqual(_event_source_kinds(build), ["terraform_sns_topic_subscription"])
        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 1)

    def test_terraform_event_source_resource_refs_are_directory_scoped(self) -> None:
        build = _extract_files(
            {
                "prod/queue.tf": 'resource "aws_sqs_queue" "orders" {\n  name = "prod-orders"\n}\n',
                "prod/events.tf": (
                    'resource "aws_lambda_event_source_mapping" "orders" {\n'
                    "  event_source_arn = aws_sqs_queue.orders.arn\n"
                    "}\n"
                ),
                "staging/queue.tf": 'resource "aws_sqs_queue" "orders" {\n  name = "staging-orders"\n}\n',
                "staging/events.tf": (
                    'resource "aws_lambda_event_source_mapping" "orders" {\n'
                    "  event_source_arn = aws_sqs_queue.orders.arn\n"
                    "}\n"
                ),
            }
        )

        self.assertEqual(_event_channels(build), [("sqs", "prod-orders"), ("sqs", "staging-orders")])

    def test_terraform_event_source_duplicate_resource_refs_fail_closed(self) -> None:
        build = _extract_files(
            {
                "events.tf": (
                    'resource "aws_sqs_queue" "orders" {\n'
                    '  name = "first-orders"\n'
                    "}\n"
                    'resource "aws_sqs_queue" "orders" {\n'
                    '  name = "second-orders"\n'
                    "}\n"
                    'resource "aws_lambda_event_source_mapping" "orders" {\n'
                    "  event_source_arn = aws_sqs_queue.orders.arn\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_event_channels(build), [])
        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 0)

    def test_terraform_event_sources_fail_closed_for_unresolved_values(self) -> None:
        build = _extract_files(
            {
                "events.tf": (
                    'resource "aws_sqs_queue" "implicit" {}\n'
                    'resource "aws_lambda_event_source_mapping" "implicit" {\n'
                    "  event_source_arn = aws_sqs_queue.implicit.arn\n"
                    "}\n"
                    'resource "aws_lambda_event_source_mapping" "interpolated" {\n'
                    '  event_source_arn = "${aws_sqs_queue.implicit.arn}"\n'
                    "}\n"
                    'resource "aws_lambda_event_source_mapping" "id_ref" {\n'
                    "  event_source_arn = aws_sqs_queue.implicit.id\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_event_channels(build), [])
        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 0)

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

    def test_cloudfront_alias_to_s3_origin_emits_runtime_route(self) -> None:
        build = _extract_files(
            {
                "variables.tf": (
                    'variable "site_domain" {\n'
                    '  default = "app.example.com"\n'
                    "}\n"
                ),
                "s3.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "  website {\n"
                    '    index_document = "index.html"\n'
                    "  }\n"
                    "}\n"
                ),
                "cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_regional_domain_name\n"
                    '    origin_id = "site-origin"\n'
                    "  }\n"
                    "  aliases = [var.site_domain]\n"
                    '  default_root_object = "index.html"\n'
                    "}\n"
                ),
            }
        )

        self.assertIn("app.example.com", _domains(build))
        self.assertEqual(_deploy_targets(build), [("cloudfront_distribution", "cloudfront.tf#aws_cloudfront_distribution.site")])
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)
        route = next(fact for fact in build.facts if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertEqual(route.qualifier["source_kind"], "terraform_cloudfront_alias")
        self.assertEqual(route.qualifier["origin_resources"], ["aws_s3_bucket.site"])
        route_evidence = next(row for row in build.evidence if row.target_type == "fact" and row.target_id == route.fact_id)
        self.assertEqual(route_evidence.bytes_ref["line_start"], 6)
        self.assertEqual(route_evidence.bytes_ref["line_end"], 6)
        reference = next(
            fact
            for fact in build.facts
            if fact.predicate == "REFERENCES_DOMAIN" and fact.qualifier["source_kind"] == "terraform_cloudfront_alias"
        )
        self.assertEqual(reference.qualifier["expression"], "var.site_domain")

    def test_cloudfront_literal_alias_emits_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertIn("static.example.com", _domains(build))
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_multiline_alias_list_emits_runtime_routes(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [\n"
                    '    "static.example.com",\n'
                    '    "www.example.com",\n'
                    "  ]\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 2)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 2)
        self.assertEqual(sorted(_domains(build)), ["static.example.com", "www.example.com"])

    def test_cloudfront_single_line_trailing_comma_alias_emits_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com",]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_duplicate_alias_emits_one_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com", "static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_runtime_routes_accept_file_iterators(self) -> None:
        build = _extract_files(
            {
                "variables.tf": (
                    'variable "site_domain" {\n'
                    '  default = "app.example.com"\n'
                    "}\n"
                ),
                "s3.tf": 'resource "aws_s3_bucket" "site" {}\n',
                "cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [var.site_domain]\n"
                    "}\n"
                ),
            },
            as_iterator=True,
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_invalid_multiline_list_does_not_hide_following_aliases(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  custom_header = [\n"
                    "    {\n"
                    '      name = "x"\n'
                    "    },\n"
                    "  ]\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_invalid_multiline_list_inside_origin_does_not_hide_domain_name(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    custom_header = [\n"
                    "      {\n"
                    '        name = "x"\n'
                    "      },\n"
                    "    ]\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_invalid_multiline_list_does_not_hide_later_origin_block(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  custom_header = [\n"
                    "    {\n"
                    '      name = "x"\n'
                    "    },\n"
                    "  ]\n"
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)

    def test_cloudfront_unclosed_alias_list_fails_closed_without_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [\n"
                    '    "static.example.com"\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_alias_malformed"])

    def test_cloudfront_unresolved_alias_emits_no_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [var.missing_domain]\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_alias_unresolved"])

    def test_cloudfront_empty_alias_list_emits_specific_coverage_reason(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = []\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_alias_empty"])

    def test_cloudfront_without_s3_origin_emits_no_runtime_route(self) -> None:
        build = _extract_files(
            {
                "cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    '    domain_name = "api.example.com"\n'
                    "  }\n"
                    '  aliases = ["app.example.com"]\n'
                    "}\n"
                ),
            }
        )

        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_no_s3_origin"])

    def test_cloudfront_malformed_origin_domain_emits_specific_coverage_reason(self) -> None:
        build = _extract_files(
            {
                "cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = ]\n"
                    "  }\n"
                    '  aliases = ["app.example.com"]\n'
                    "}\n"
                ),
            }
        )

        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_origin_domain_malformed"])

    def test_cloudfront_variable_resolution_is_directory_scoped(self) -> None:
        build = _extract_files(
            {
                "prod/variables.tf": (
                    'variable "site_domain" {\n'
                    '  default = "prod.example.com"\n'
                    "}\n"
                ),
                "staging/variables.tf": (
                    'variable "site_domain" {\n'
                    '  default = "staging.example.com"\n'
                    "}\n"
                ),
                "prod/s3.tf": 'resource "aws_s3_bucket" "site" {}\n',
                "staging/s3.tf": 'resource "aws_s3_bucket" "site" {}\n',
                "prod/cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [var.site_domain]\n"
                    "}\n"
                ),
                "staging/cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [var.site_domain]\n"
                    "}\n"
                ),
            }
        )

        routes = [
            (
                _entity_name(build, fact.subject_id),
                _entity_target(build, fact.object_id),
            )
            for fact in build.facts
            if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY"
        ]
        self.assertEqual(
            sorted(routes),
            [
                ("prod.example.com", "prod/cloudfront.tf#aws_cloudfront_distribution.site"),
                ("staging.example.com", "staging/cloudfront.tf#aws_cloudfront_distribution.site"),
            ],
        )

    def test_cloudfront_s3_origin_resolution_is_directory_scoped(self) -> None:
        build = _extract_files(
            {
                "prod/variables.tf": (
                    'variable "site_domain" {\n'
                    '  default = "prod.example.com"\n'
                    "}\n"
                ),
                "staging/s3.tf": 'resource "aws_s3_bucket" "site" {}\n',
                "prod/cloudfront.tf": (
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "  aliases = [var.site_domain]\n"
                    "}\n"
                ),
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_no_s3_origin"])

    def test_cloudfront_missing_alias_emits_coverage(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
                    "  }\n"
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_alias_missing"])

    def test_cloudfront_invalid_resource_reference_emits_no_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    "    domain_name = aws_s3_bucket.123-site.bucket_domain_name\n"
                    "  }\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_no_s3_origin"])

    def test_cloudfront_function_wrapped_resource_reference_emits_no_runtime_route(self) -> None:
        build = _extract_files(
            {
                "main.tf": (
                    'resource "aws_s3_bucket" "site" {\n'
                    '  bucket = "example-site"\n'
                    "}\n"
                    'resource "aws_cloudfront_distribution" "site" {\n'
                    "  origin {\n"
                    '    domain_name = lookup(local.origins, "site", aws_s3_bucket.site.bucket_domain_name)\n'
                    "  }\n"
                    '  aliases = ["static.example.com"]\n'
                    "}\n"
                )
            }
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_coverage_reasons(build), ["cloudfront_no_s3_origin"])

    def test_legacy_single_file_api_emits_coverage_when_runtime_routes_are_skipped(self) -> None:
        build = _extract(
            'resource "aws_s3_bucket" "site" {\n'
            '  bucket = "example-site"\n'
            "}\n"
            'resource "aws_cloudfront_distribution" "site" {\n'
            "  origin {\n"
            "    domain_name = aws_s3_bucket.site.bucket_domain_name\n"
            "  }\n"
            '  aliases = ["static.example.com"]\n'
            "}\n"
        )

        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 0)
        self.assertEqual(_coverage_reasons(build), ["terraform_runtime_requires_file_set_api"])
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)

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
    return _extract_files({relative_path: text}, single_file_api=True)


def _extract_files(
    files: dict[str, str],
    *,
    single_file_api: bool = False,
    as_iterator: bool = False,
) -> ConfigKgBuild:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        scanned_files = []
        for relative_path, text in files.items():
            terraform_path = root / relative_path
            terraform_path.parent.mkdir(parents=True, exist_ok=True)
            terraform_path.write_text(text, encoding="utf-8")
            scanned_files.append(
                ScannedFile(
                    path=terraform_path,
                    relative_path=relative_path,
                    text=text,
                    lines=tuple(text.splitlines()),
                )
            )
        repo = RepoSnapshot(
            root=root,
            name="terraform-service",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (), "typescript": ()},
        )
        service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
        build = ConfigKgBuild()
        if single_file_api:
            self_scanned = scanned_files[0]
            extract_terraform(repo, self_scanned, service, build, "default")
        else:
            file_input = iter(scanned_files) if as_iterator else scanned_files
            extract_terraform_files(repo, file_input, service, build, "default")
        return build


def _domains(build: ConfigKgBuild) -> list[str]:
    return [entity.identity["name"] for entity in build.entities if entity.kind == "Domain"]


def _fact_count(build: ConfigKgBuild, predicate: str) -> int:
    return len([fact for fact in build.facts if fact.predicate == predicate])


def _deploy_targets(build: ConfigKgBuild) -> list[tuple[str, str]]:
    return [
        (entity.identity["type"], entity.identity["target"])
        for entity in build.entities
        if entity.kind == "DeployTarget"
    ]


def _event_channels(build: ConfigKgBuild) -> list[tuple[str, str]]:
    return sorted(
        (entity.identity["broker_kind"], entity.identity["channel_address"])
        for entity in build.entities
        if entity.kind == "EventChannel"
    )


def _event_source_kinds(build: ConfigKgBuild) -> list[str]:
    return sorted({fact.qualifier["source_kind"] for fact in build.facts if fact.predicate == "CONSUMES_EVENT"})


def _coverage_reasons(build: ConfigKgBuild) -> list[str]:
    return sorted(
        str(row.scope_ref["reason"])
        for row in build.coverage
        if row.predicate == "ROUTES_DOMAIN_TO_DEPLOY"
    )


def _entity_name(build: ConfigKgBuild, entity_id: str) -> str:
    entity = next(entity for entity in build.entities if entity.entity_id == entity_id)
    return str(entity.identity["name"])


def _entity_target(build: ConfigKgBuild, entity_id: str) -> str:
    entity = next(entity for entity in build.entities if entity.entity_id == entity_id)
    return str(entity.identity["target"])


if __name__ == "__main__":
    unittest.main()
