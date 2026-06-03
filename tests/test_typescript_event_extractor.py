from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.message_events import extract_typescript_message_events
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo


NODE_AVAILABLE = shutil.which("node") is not None


def _events(tmp: str, files: dict[str, str]) -> ConfigKgBuild:
    root = Path(tmp)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    repo = discover_repo(root)
    build = ConfigKgBuild()
    service = StaticConfigExtractor()._service_entity(repo, "default")
    extract_typescript_message_events(repo, parse_typescript_repo(repo), service, build, "default")
    return build


_NEST_CONTROLLER = """import { EventPattern, MessagePattern, ClientKafka } from '@nestjs/microservices';

export class OrderController {
  constructor(private readonly client: ClientKafka) {}

  @MessagePattern('order_create')
  create(data: any) {}

  @EventPattern('order_failed')
  onFailed(data: any) {}

  publish() {
    this.client.emit('inventory_new_order', {});
    this.client.send('payment_create', {});
  }
}
"""


@unittest.skipIf(not NODE_AVAILABLE, "node executable not available for the TypeScript parser bridge")
class TypescriptEventExtractorTest(unittest.TestCase):
    def test_nestjs_consumers_and_clientproxy_producers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build = _events(tmp, {"order.controller.ts": _NEST_CONTROLLER})

        channels = {e.identity["channel_address"]: e.identity["broker_kind"] for e in build.entities if e.kind == "EventChannel"}
        self.assertEqual(set(channels), {"order_create", "order_failed", "inventory_new_order", "payment_create"})
        self.assertTrue(all(broker == "nestjs" for broker in channels.values()))
        consumes = {_channel(build, f) for f in build.facts if f.predicate == "CONSUMES_EVENT"}
        produces = {_channel(build, f) for f in build.facts if f.predicate == "PRODUCES_EVENT"}
        self.assertEqual(consumes, {"order_create", "order_failed"})
        self.assertEqual(produces, {"inventory_new_order", "payment_create"})

    def test_no_events_without_nest_microservices_import(self) -> None:
        # The @nestjs/microservices import gate keeps unrelated decorators/calls out.
        source = _NEST_CONTROLLER.replace(
            "import { EventPattern, MessagePattern, ClientKafka } from '@nestjs/microservices';\n", ""
        )
        with tempfile.TemporaryDirectory() as tmp:
            build = _events(tmp, {"order.controller.ts": source})

        self.assertEqual([f for f in build.facts if f.predicate in {"PRODUCES_EVENT", "CONSUMES_EVENT"}], [])

    def test_emit_on_non_client_member_is_not_a_producer(self) -> None:
        # `.emit`/`.send` are generic; only receivers typed as a Nest client count.
        source = """import { EventPattern, ClientKafka } from '@nestjs/microservices';
import { EventEmitter } from 'events';

export class Worker {
  constructor(private readonly bus: EventEmitter) {}

  @EventPattern('order_failed')
  onFailed(data: any) {}

  go() {
    this.bus.emit('not_an_event', {});
  }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _events(tmp, {"worker.ts": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(produces, [])
        consumes = [f for f in build.facts if f.predicate == "CONSUMES_EVENT"]
        self.assertEqual(len(consumes), 1)  # the @EventPattern consumer still fires

    def test_bare_identifier_emit_is_not_a_producer(self) -> None:
        # A bare `client.emit(...)` is a local/param, not the `this.client` member, so it must not
        # be attributed to the class's injected client even when a same-named member exists.
        source = """import { ClientKafka } from '@nestjs/microservices';

export class Worker {
  constructor(private readonly client: ClientKafka) {}

  go() {
    const client = makeEmitter();
    client.emit('local_not_an_event', {});
  }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _events(tmp, {"worker.ts": source})

        self.assertEqual([f for f in build.facts if f.predicate == "PRODUCES_EVENT"], [])

    def test_non_literal_channel_emits_coverage_not_a_guess(self) -> None:
        source = """import { EventPattern, ClientKafka } from '@nestjs/microservices';

const TOPIC = process.env.TOPIC;

export class Worker {
  constructor(private readonly client: ClientKafka) {}

  go() {
    this.client.emit(TOPIC, {});
  }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _events(tmp, {"worker.ts": source})

        self.assertEqual([f for f in build.facts if f.predicate == "PRODUCES_EVENT"], [])
        unresolved = [c for c in build.coverage if c.scope_ref.get("reason") == "unresolved_event_channel"]
        self.assertEqual(len(unresolved), 1)


def _channel(build: ConfigKgBuild, fact: object) -> str:
    by_id = {e.entity_id: e for e in build.entities}
    return by_id[fact.object_id].identity["channel_address"]


if __name__ == "__main__":
    unittest.main()
