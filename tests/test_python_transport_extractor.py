from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.python.ast_extractor import PythonAstExtractor


class PythonTransportExtractorTest(unittest.TestCase):
    def test_boto3_sqs_client_send_message_emits_produces_event(self) -> None:
        source = (
            "import boto3 as aws\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = aws.client("sqs")\n'
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(fact.predicate, "PRODUCES_EVENT")
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(channel.properties["queue_url"], "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.client('sqs').send_message")
        self.assertEqual(fact.qualifier["raw_literal"], "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created")
        evidence = [row for row in build.evidence if row.target_id == fact.fact_id]
        self.assertEqual(evidence[0].derivation_class, "deterministic_static")

    def test_boto3_sqs_chained_client_call_emits_produces_event(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order():\n"
            '    boto3.client("sqs").send_message_batch('
            'QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/orders-created", Entries=[])\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.client('sqs').send_message_batch")

    def test_boto3_client_service_name_keyword_emits_produces_event(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.client(service_name="sqs")\n'
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.client('sqs').send_message")

    def test_boto3_annotated_client_assignment_emits_produces_event(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs: object = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.client('sqs').send_message")

    def test_boto3_sns_publish_with_imported_constant_emits_produces_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "app"
            package.mkdir()
            (package / "settings.py").write_text(
                'TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:orders-created"\n',
                encoding="utf-8",
            )
            producer = package / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app.settings import TOPIC_ARN\n\n"
                "def publish_order():\n"
                '    sns = boto3.client("sns")\n'
                '    sns.publish(TopicArn=TOPIC_ARN, Message="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (package / "settings.py", producer))

            build = PythonAstExtractor().extract(repo)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sns")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(channel.properties["arn"], "arn:aws:sns:us-east-1:123456789012:orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.client('sns').publish")

    def test_boto3_sqs_resource_queue_uses_queue_factory_argument(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.resource("sqs")\n'
            "    queue = sqs.Queue(QUEUE_URL)\n"
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.resource('sqs').Queue(...).send_message")

    def test_boto3_sqs_resource_queue_accepts_url_keyword(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.resource("sqs")\n'
            "    queue = sqs.Queue(url=QUEUE_URL)\n"
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.resource('sqs').Queue(...).send_message")

    def test_boto3_annotated_queue_assignment_emits_produces_event(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs: object = boto3.resource("sqs")\n'
            "    queue: object = sqs.Queue(QUEUE_URL)\n"
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.resource('sqs').Queue(...).send_message")

    def test_unresolved_transport_channel_emits_coverage_not_fact(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order(queue_url):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=queue_url, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unknown_name")
        self.assertEqual(unresolved[0].scope_ref["expression"], "queue_url")

    def test_unsupported_transport_channel_literal_emits_coverage_not_fact(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl="orders-created", MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unsupported_channel_literal")
        self.assertEqual(unresolved[0].scope_ref["expression"], "'orders-created'")

    def test_local_wrapper_with_resolved_channel_emits_static_inferred_producer(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")
        self.assertEqual(fact.qualifier["promotion"], "local_wrapper_body")
        self.assertEqual(fact.qualifier["wrapper_depth"], 1)
        evidence = [row for row in build.evidence if row.target_id == fact.fact_id]
        self.assertEqual(evidence[0].derivation_class, "static_inferred")

    def test_local_wrapper_keyword_argument_emits_static_inferred_producer(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(destination=QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")
        evidence = [row for row in build.evidence if row.target_id == fact.fact_id]
        self.assertEqual(evidence[0].derivation_class, "static_inferred")

    def test_positional_only_wrapper_param_is_not_bound_by_keyword(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination, /):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(destination=QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertTrue(unresolved)
        self.assertTrue(any(row.scope_ref["reason"] == "unknown_name" for row in unresolved))

    def test_duplicate_wrapper_arg_binding_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n'
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(QUEUE_URL, destination=OTHER_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_unexpected_wrapper_keyword_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(unexpected=QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_wrapper_promotion_does_not_depend_on_wrapper_name(self) -> None:
        for wrapper_name in ("alpha", "send_message"):
            with self.subTest(wrapper_name=wrapper_name):
                source = (
                    "import boto3\n\n"
                    'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
                    f"def {wrapper_name}(destination):\n"
                    '    sqs = boto3.client("sqs")\n'
                    '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
                    "def publish_order():\n"
                    f"    {wrapper_name}(QUEUE_URL)\n"
                )

                build = _extract_single_file(source)

                fact, channel = _single_event_fact(build.facts, build.entities)
                self.assertEqual(channel.identity["broker_kind"], "sqs")
                self.assertEqual(channel.identity["channel_address"], "orders-created")
                self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")

    def test_local_assignment_shadowing_wrapper_name_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    sender = lambda destination: None\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_parameter_shadowing_wrapper_name_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order(sender):\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_import_and_for_shadowing_wrapper_name_block_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    import sender\n"
            "    for sender in []:\n"
            "        pass\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_nested_function_default_binding_shadows_wrapper_name(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    def inner(value=(sender := None)):\n"
            "        pass\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_nested_class_base_binding_shadows_wrapper_name(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    class Inner((sender := object)):\n"
            "        pass\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_wrapper_local_rebinding_overrides_call_site_binding(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n'
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def renamed_wrapper(destination):\n"
            "    destination = OTHER_URL\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertTrue(event_facts)
        self.assertEqual({channels_by_id[fact.object_id].identity["channel_address"] for fact in event_facts}, {"other"})
        self.assertTrue(any(fact.qualifier["source_kind"] == "python_transport_wrapper_call" for fact in event_facts))

    def test_nested_local_wrapper_promotion_is_bounded_and_static_inferred(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def inner(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def outer(destination):\n"
            "    inner(destination)\n\n"
            "def publish_order():\n"
            "    outer(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")
        self.assertEqual(fact.qualifier["wrapper_depth"], 2)
        evidence = [row for row in build.evidence if row.target_id == fact.fact_id]
        self.assertEqual(evidence[0].derivation_class, "static_inferred")

    def test_nested_function_body_is_not_treated_as_outer_transport_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            "    def inner():\n"
            '        sqs = boto3.client("sqs")\n'
            '        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_lambda_body_is_not_treated_as_outer_transport_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            "    sqs = boto3.client('sqs')\n"
            '    delayed = lambda: sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_nested_function_default_expression_is_treated_as_outer_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    def inner(result=sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")):\n'
            "        pass\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_api_call")

    def test_nested_class_base_expression_is_treated_as_outer_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def base(value):\n"
            "    return object\n\n"
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    class Inner(base(sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}"))):\n'
            "        pass\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_api_call")

    def test_user_defined_client_name_does_not_emit_event_without_boto3_import(self) -> None:
        source = (
            "class boto3:\n"
            "    @staticmethod\n"
            "    def client(name):\n"
            "        return object()\n\n"
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl="orders-created", MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)


def _extract_single_file(source: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        path = root / "producer.py"
        path.write_text(source, encoding="utf-8")
        repo = _repo_snapshot(root, (path,))
        return PythonAstExtractor().extract(repo)


def _repo_snapshot(root: Path, python_files: tuple[Path, ...]) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        python_files=python_files,
        typescript_files=(),
    )


def _single_event_fact(facts: list[Fact], entities: list[Entity]) -> tuple[Fact, Entity]:
    event_facts = [fact for fact in facts if fact.predicate == "PRODUCES_EVENT"]
    channels_by_id = {entity.entity_id: entity for entity in entities if entity.kind == "EventChannel"}
    if len(event_facts) != 1:
        raise AssertionError(f"expected exactly one PRODUCES_EVENT fact, got {len(event_facts)}")
    channel = channels_by_id[event_facts[0].object_id]
    return event_facts[0], channel


if __name__ == "__main__":
    unittest.main()
