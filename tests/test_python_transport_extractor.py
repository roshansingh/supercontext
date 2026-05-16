from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.models import Entity, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.python.extractors.ast_extractor import PythonAstExtractor
from source.kg.languages.python.extractors.transport_extractor import module_transport_context


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

    def test_boto3_get_queue_by_name_accepts_bare_queue_name(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order():\n"
            '    sqs = boto3.resource("sqs")\n'
            '    queue = sqs.get_queue_by_name(QueueName="orders-created")\n'
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["api"], "boto3.resource('sqs').Queue(...).send_message")

    def test_set_resolved_queue_names_emit_deterministic_channel_order(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_NAMES = {"z-orders", "a-orders"}\n\n'
            "def publish_order():\n"
            '    sqs = boto3.resource("sqs")\n'
            "    queue = sqs.get_queue_by_name(QueueName=QUEUE_NAMES)\n"
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(
            [channels_by_id[fact.object_id].identity["channel_address"] for fact in event_facts],
            ["a-orders", "z-orders"],
        )

    def test_bare_queue_name_does_not_resolve_for_queue_url_argument(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl="orders-created", MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT"]
        self.assertEqual(unresolved[0].scope_ref["reason"], "unsupported_channel_literal")

    def test_module_level_queue_resource_resolves_imported_settings_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_dir = root / "app" / "settings"
            settings_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (settings_dir / "__init__.py").write_text("", encoding="utf-8")
            (settings_dir / "dev.py").write_text('QUEUE_NAME = "dev-orders"\n', encoding="utf-8")
            (settings_dir / "prod.py").write_text('QUEUE_NAME = "prod-orders"\n', encoding="utf-8")
            producer = root / "app" / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app import settings\n\n"
                'sqs = boto3.resource("sqs")\n'
                "queue = sqs.get_queue_by_name(QueueName=settings.QUEUE_NAME)\n\n"
                "def publish_order():\n"
                '    queue.send_message(MessageBody="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (settings_dir / "__init__.py", settings_dir / "dev.py", settings_dir / "prod.py", producer))

            build = PythonAstExtractor().extract(repo)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(
            {channels_by_id[fact.object_id].identity["channel_address"] for fact in event_facts},
            {"dev-orders", "prod-orders"},
        )

    def test_direct_settings_import_resolves_environment_variants_for_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings_dir = root / "app" / "settings"
            settings_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (settings_dir / "__init__.py").write_text("", encoding="utf-8")
            (settings_dir / "dev.py").write_text('QUEUE_NAME = "dev-orders"\n', encoding="utf-8")
            (settings_dir / "prod.py").write_text('QUEUE_NAME = "prod-orders"\n', encoding="utf-8")
            consumer = root / "app" / "consumer.py"
            consumer.write_text(
                "import boto3\n"
                "from app.settings import QUEUE_NAME\n\n"
                "def consume_orders():\n"
                '    sqs = boto3.resource("sqs")\n'
                "    queue = sqs.get_queue_by_name(QueueName=QUEUE_NAME)\n"
                "    queue.receive_messages(MaxNumberOfMessages=5)\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (settings_dir / "__init__.py", settings_dir / "dev.py", settings_dir / "prod.py", consumer))

            build = PythonAstExtractor().extract(repo)

        event_facts = [fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(
            {channels_by_id[fact.object_id].identity["channel_address"] for fact in event_facts},
            {"dev-orders", "prod-orders"},
        )

    def test_control_flow_queue_resource_resolves_config_ini_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (config_dir / "prod.ini").write_text("[messaging]\nemail_queue = prod-email\n", encoding="utf-8")
            (config_dir / "__init__.py").write_text(
                "import configparser\n\n"
                "parser = configparser.ConfigParser()\n"
                "parser.read('prod.ini')\n\n"
                "class QueueConfig:\n"
                "    def __init__(self):\n"
                "        self.EMAIL_QUEUE = parser['messaging']['email_queue']\n\n"
                "class AppConfig:\n"
                "    def __init__(self):\n"
                "        self.queueConfig = QueueConfig()\n\n"
                "settings = AppConfig()\n",
                encoding="utf-8",
            )
            producer = root / "app" / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app.configmanager import settings\n\n"
                "email_sqs_queue = None\n\n"
                "def publish_order():\n"
                "    global email_sqs_queue\n"
                "    if not email_sqs_queue:\n"
                '        sqs = boto3.resource("sqs")\n'
                "        email_sqs_queue = sqs.get_queue_by_name(QueueName=settings.queueConfig.EMAIL_QUEUE)\n"
                '    email_sqs_queue.send_message(MessageBody="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_dir / "__init__.py", producer))

            build = PythonAstExtractor().extract(repo)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["channel_address"], "prod-email")
        self.assertEqual(fact.predicate, "PRODUCES_EVENT")
        self.assertEqual(
            fact.qualifier["resolution"]["source_refs"],
            [
                {
                    "source_kind": "configparser_ini_option",
                    "path": "app/configmanager/prod.ini",
                    "line_start": 2,
                    "line_end": 2,
                    "section": "messaging",
                    "option": "email_queue",
                }
            ],
        )

    def test_configparser_default_ini_value_resolves_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (config_dir / "prod.ini").write_text(
                "[DEFAULT]\nemail_queue = default-email\n\n[queue]\nother = ignored-value\n",
                encoding="utf-8",
            )
            (config_dir / "__init__.py").write_text(
                "import configparser\n\n"
                "class Config:\n"
                "    def __init__(self):\n"
                "        parser = configparser.ConfigParser()\n"
                "        parser.read('prod.ini')\n"
                "        self.queueConfig = QueueConfig(parser)\n\n"
                "class QueueConfig:\n"
                "    def __init__(self, parser):\n"
                "        self.EMAIL_QUEUE = parser['queue']['email_queue']\n\n"
                "config = Config()\n",
                encoding="utf-8",
            )
            producer = root / "app" / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app.configmanager import config\n\n"
                "def publish_order():\n"
                '    sqs = boto3.resource("sqs")\n'
                "    queue = sqs.get_queue_by_name(QueueName=config.queueConfig.EMAIL_QUEUE)\n"
                '    queue.send_message(MessageBody="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_dir / "__init__.py", producer))

            build = PythonAstExtractor().extract(repo)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(len(event_facts), 1)
        self.assertEqual(channels_by_id[event_facts[0].object_id].identity["channel_address"], "default-email")

    def test_configparser_argument_passed_to_child_config_class_resolves_ini_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (config_dir / "prod.ini").write_text("[queue]\nemail_queue = prod-email\n", encoding="utf-8")
            (config_dir / "__init__.py").write_text(
                "import configparser\n\n"
                "class Config:\n"
                "    def __init__(self):\n"
                "        parser = configparser.ConfigParser()\n"
                "        parser.read('prod.ini')\n"
                "        self.queueConfig = QueueConfig(parser)\n\n"
                "class QueueConfig:\n"
                "    def __init__(self, parser):\n"
                "        self.EMAIL_QUEUE = parser['queue']['email_queue']\n\n"
                "config = Config()\n",
                encoding="utf-8",
            )
            producer = root / "app" / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app.configmanager import config\n\n"
                "def publish_order():\n"
                '    sqs = boto3.resource("sqs")\n'
                "    queue = sqs.get_queue_by_name(QueueName=config.queueConfig.EMAIL_QUEUE)\n"
                '    queue.send_message(MessageBody="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_dir / "__init__.py", producer))

            build = PythonAstExtractor().extract(repo)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["channel_address"], "prod-email")
        self.assertEqual(fact.predicate, "PRODUCES_EVENT")

    def test_configparser_source_refs_survive_local_wrapper_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            (root / "app" / "__init__.py").write_text("", encoding="utf-8")
            (config_dir / "prod.ini").write_text("[queue]\nemail_queue = prod-email\n", encoding="utf-8")
            (config_dir / "__init__.py").write_text(
                "import configparser\n\n"
                "class QueueConfig:\n"
                "    def __init__(self):\n"
                "        parser = configparser.ConfigParser()\n"
                "        parser.read('prod.ini')\n"
                "        self.EMAIL_QUEUE = parser['queue']['email_queue']\n\n"
                "settings = QueueConfig()\n",
                encoding="utf-8",
            )
            producer = root / "app" / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app.configmanager import settings\n\n"
                "def publish(queue_name):\n"
                '    sqs = boto3.resource("sqs")\n'
                "    queue = sqs.get_queue_by_name(QueueName=queue_name)\n"
                '    queue.send_message(MessageBody="{}")\n\n'
                "def publish_order():\n"
                "    publish(settings.EMAIL_QUEUE)\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_dir / "__init__.py", producer))

            build = PythonAstExtractor().extract(repo)

        fact, _ = _single_event_fact(build.facts, build.entities)
        self.assertEqual(fact.qualifier["resolution"]["source_refs"][0]["path"], "app/configmanager/prod.ini")

    def test_ini_files_do_not_pollute_python_literal_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "app"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (root / "pytest.ini").write_text("[pytest]\nasyncio_mode = auto\n", encoding="utf-8")
            (root / "setup.ini").write_text("[flake8]\nmax-line-length = 88\n", encoding="utf-8")
            producer = package / "producer.py"
            producer.write_text(
                "import boto3\n"
                "from app import settings\n\n"
                "def publish_order():\n"
                '    sqs = boto3.resource("sqs")\n'
                "    queue = sqs.get_queue_by_name(QueueName=settings.MAX_LINE_LENGTH)\n"
                '    queue.send_message(MessageBody="{}")\n',
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (producer,))

            build = PythonAstExtractor().extract(repo)

        self.assertFalse([fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"])
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unknown_attribute_root")

    def test_sqs_receive_messages_emits_consumes_event(self) -> None:
        source = (
            "import boto3\n\n"
            "def consume_orders():\n"
            '    sqs = boto3.resource("sqs")\n'
            '    queue = sqs.get_queue_by_name(QueueName="orders-created")\n'
            "    for message in queue.receive_messages(MaxNumberOfMessages=10):\n"
            "        pass\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(len(event_facts), 1)
        self.assertEqual(channels_by_id[event_facts[0].object_id].identity["channel_address"], "orders-created")
        self.assertEqual(event_facts[0].qualifier["api"], "boto3.resource('sqs').Queue(...).receive_messages")

    def test_sqs_client_receive_message_emits_consumes_event_for_queue_url(self) -> None:
        source = (
            "import boto3\n\n"
            "def consume_orders():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.receive_message(QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/orders-created")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertEqual(len(event_facts), 1)
        self.assertEqual(channels_by_id[event_facts[0].object_id].identity["channel_address"], "orders-created")
        self.assertEqual(event_facts[0].qualifier["api"], "boto3.client('sqs').receive_message")

    def test_sqs_client_receive_message_rejects_bare_queue_name(self) -> None:
        source = (
            "import boto3\n\n"
            "def consume_orders():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.receive_message(QueueUrl="orders-created")\n'
        )

        build = _extract_single_file(source)

        self.assertFalse([fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT"])
        unresolved = [row for row in build.coverage if row.predicate == "CONSUMES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unsupported_channel_literal")

    def test_ambiguous_queue_resource_assignments_fail_closed(self) -> None:
        source = (
            "import boto3\n\n"
            "def publish_order(flag):\n"
            '    sqs = boto3.resource("sqs")\n'
            "    if flag:\n"
            '        queue = sqs.get_queue_by_name(QueueName="orders-created")\n'
            "    else:\n"
            '        queue = sqs.get_queue_by_name(QueueName="other-orders")\n'
            '    queue.send_message(MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

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
        self.assertEqual(unresolved[0].scope_ref["reason"], "unknown_local_binding")
        self.assertEqual(unresolved[0].scope_ref["expression"], "queue_url")

    def test_later_local_channel_assignment_does_not_resolve_earlier_call(self) -> None:
        source = (
            "import boto3\n\n"
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=queue_url, MessageBody="{}")\n'
            "    queue_url = OTHER_URL\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unknown_local_binding")
        self.assertEqual(unresolved[0].scope_ref["expression"], "queue_url")

    def test_later_client_assignment_does_not_make_earlier_call_a_transport_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
            '    sqs = boto3.client("sqs")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_later_queue_resource_assignment_does_not_resolve_earlier_resource_call(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order():\n"
            '    sqs = boto3.resource("sqs")\n'
            '    queue.send_message(MessageBody="{}")\n'
            "    queue = sqs.Queue(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_local_parameter_does_not_fall_back_to_same_named_module_channel(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def publish_order(QUEUE_URL):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)
        unresolved = [row for row in build.coverage if row.predicate == "PRODUCES_EVENT" and row.state == "uninstrumented"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].scope_ref["reason"], "unknown_local_binding")
        self.assertEqual(unresolved[0].scope_ref["expression"], "QUEUE_URL")

    def test_global_declaration_allows_module_channel_resolution_before_assignment(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n'
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def publish_order():\n"
            "    global QUEUE_URL\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody="{}")\n'
            "    QUEUE_URL = OTHER_URL\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_api_call")

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

    def test_local_literal_wrapper_argument_can_shadow_same_named_module_channel(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    queue_url = QUEUE_URL\n"
            "    renamed_wrapper(queue_url)\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")

    def test_unresolved_local_wrapper_argument_does_not_fall_back_to_same_named_module_channel(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def compute_queue_url():\n"
            "    return 'runtime-only'\n\n"
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    QUEUE_URL = compute_queue_url()\n"
            "    renamed_wrapper(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_parameter_wrapper_argument_does_not_fall_back_to_same_named_module_channel(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order(QUEUE_URL):\n"
            "    renamed_wrapper(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

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

    def test_missing_required_wrapper_positional_arg_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper()\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_missing_required_wrapper_keyword_only_arg_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            "def renamed_wrapper(*, destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    renamed_wrapper()\n"
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

    def test_match_capture_shadowing_wrapper_name_blocks_promotion(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order(value):\n"
            "    match value:\n"
            "        case {'sender': sender}:\n"
            "            pass\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        self.assertFalse(event_facts)

    def test_global_declaration_does_not_shadow_wrapper_name(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n\n'
            "def sender(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    global sender\n"
            "    sender(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        fact, channel = _single_event_fact(build.facts, build.entities)
        self.assertEqual(channel.identity["broker_kind"], "sqs")
        self.assertEqual(channel.identity["channel_address"], "orders-created")
        self.assertEqual(fact.qualifier["source_kind"], "python_transport_wrapper_call")

    def test_multi_producer_wrapper_fails_closed(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n'
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def send_both(first, second):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=first, MessageBody="{}")\n'
            '    sqs.send_message(QueueUrl=second, MessageBody="{}")\n\n'
            "def publish_order():\n"
            "    send_both(QUEUE_URL, OTHER_URL)\n"
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

    def test_wrapper_later_local_rebinding_does_not_override_earlier_call_site_binding(self) -> None:
        source = (
            "import boto3\n\n"
            'QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"\n'
            'OTHER_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/other"\n\n'
            "def renamed_wrapper(destination):\n"
            '    sqs = boto3.client("sqs")\n'
            '    sqs.send_message(QueueUrl=destination, MessageBody="{}")\n'
            "    destination = OTHER_URL\n\n"
            "def publish_order():\n"
            "    renamed_wrapper(QUEUE_URL)\n"
        )

        build = _extract_single_file(source)

        event_facts = [fact for fact in build.facts if fact.predicate == "PRODUCES_EVENT"]
        channels_by_id = {entity.entity_id: entity for entity in build.entities if entity.kind == "EventChannel"}
        self.assertTrue(event_facts)
        self.assertEqual({channels_by_id[fact.object_id].identity["channel_address"] for fact in event_facts}, {"orders-created"})
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

    def test_module_transport_context_is_built_once_per_file(self) -> None:
        source = (
            "import boto3\n\n"
            'sqs = boto3.resource("sqs")\n'
            'queue = sqs.get_queue_by_name(QueueName="orders-created")\n\n'
            "def publish_order():\n"
            '    queue.send_message(MessageBody="{}")\n\n'
            "def publish_again():\n"
            '    queue.send_message(MessageBody="{}")\n'
        )

        with patch(
            "source.kg.languages.python.extractors.ast_extractor.module_transport_context",
            wraps=module_transport_context,
        ) as context_builder:
            _extract_single_file(source)

        self.assertEqual(context_builder.call_count, 1)


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
