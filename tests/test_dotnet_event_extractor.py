from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.languages.dotnet.extractors.csharp_extractor import CSharpExtractor


_MASSTRANSIT_CONSUMER = """using MassTransit;
namespace App.Consumers;
public class OrderConsumer : IConsumer<OrderSubmitted>
{
    public async Task Consume(ConsumeContext<OrderSubmitted> context) { }
}
"""


def _dotnet_dependencies_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c_sharp  # noqa: F401
    except ImportError:
        return False
    return True


DOTNET_AVAILABLE = _dotnet_dependencies_available()


def _extract(tmp: str, files: dict[str, str]) -> object:
    root = Path(tmp)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return CSharpExtractor().extract(discover_repo(root))


@unittest.skipIf(not DOTNET_AVAILABLE, "tree-sitter and tree-sitter-c-sharp not installed; install with pip install -e '.[dotnet]'")
class DotnetEventExtractorTest(unittest.TestCase):
    def test_masstransit_consumer_emits_consumes_event_on_message_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"OrderConsumer.cs": _MASSTRANSIT_CONSUMER})

        channels = [e for e in build.entities if e.kind == "EventChannel"]
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].identity["broker_kind"], "masstransit")
        self.assertEqual(channels[0].identity["channel_address"], "OrderSubmitted")
        consumes = [f for f in build.facts if f.predicate == "CONSUMES_EVENT"]
        self.assertEqual(len(consumes), 1)
        self.assertEqual(consumes[0].object_id, channels[0].entity_id)
        self.assertEqual(consumes[0].qualifier["broker_kind"], "masstransit")

    def test_iconsumer_without_masstransit_import_is_not_an_event(self) -> None:
        # An IConsumer<T> from an unrelated library must not enter the event graph.
        source = _MASSTRANSIT_CONSUMER.replace("using MassTransit;\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"OrderConsumer.cs": source})

        self.assertEqual([f for f in build.facts if f.predicate == "CONSUMES_EVENT"], [])
        self.assertEqual([e for e in build.entities if e.kind == "EventChannel"], [])

    def test_mediatr_publish_and_send_are_not_events(self) -> None:
        # Publish/Send method names collide with MediatR; the receiver type must gate them out.
        source = """using MediatR;
namespace App;
public class Handler
{
    private readonly ISender sender;
    private readonly IMediator mediator;
    public async Task Do(object cmd)
    {
        await sender.Send(cmd);
        await mediator.Publish(cmd);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Handler.cs": source})

        events = [f for f in build.facts if f.predicate in {"PRODUCES_EVENT", "CONSUMES_EVENT"}]
        self.assertEqual(events, [])

    def test_integration_event_handler_consumes_even_without_local_import(self) -> None:
        # eShop uses implicit/global usings; IIntegrationEventHandler is distinctive, so ungated.
        source = """namespace App;
public class StartedHandler(ILogger logger) : IIntegrationEventHandler<OrderStarted>
{
    public Task Handle(OrderStarted e) => Task.CompletedTask;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"StartedHandler.cs": source})

        consumes = [f for f in build.facts if f.predicate == "CONSUMES_EVENT"]
        self.assertEqual(len(consumes), 1)
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["broker_kind"], "integration_event")
        self.assertEqual(channel.identity["channel_address"], "OrderStarted")

    def test_masstransit_producer_resolves_local_message_type(self) -> None:
        source = """using MassTransit;
namespace App;
public class Sender(IPublishEndpoint publishEndpoint)
{
    public async Task Go()
    {
        var msg = new OrderSubmitted();
        await publishEndpoint.Publish(msg);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Sender.cs": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(len(produces), 1)
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["broker_kind"], "masstransit")
        self.assertEqual(channel.identity["channel_address"], "OrderSubmitted")

    def test_eventbus_producer_resolves_inline_new_message(self) -> None:
        source = """namespace App;
public class Svc(IEventBus eventBus)
{
    public async Task Go()
    {
        await eventBus.PublishAsync(new PaymentCaptured());
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Svc.cs": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(len(produces), 1)
        self.assertEqual(produces[0].qualifier["broker_kind"], "integration_event")
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["channel_address"], "PaymentCaptured")

    def test_producer_resolves_explicit_declared_local_type(self) -> None:
        # `OrderSubmitted msg = Build();` -> the declared type resolves even when the
        # initializer's return type isn't statically visible.
        source = """using MassTransit;
namespace App;
public class Sender(IPublishEndpoint publishEndpoint)
{
    public async Task Go()
    {
        OrderSubmitted msg = Build();
        await publishEndpoint.Publish(msg);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Sender.cs": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(len(produces), 1)
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["channel_address"], "OrderSubmitted")

    def test_object_declared_local_defers_to_initializer_not_object_channel(self) -> None:
        # `object msg = new OrderSubmitted()` must resolve OrderSubmitted, never a channel named "object".
        source = """using MassTransit;
namespace App;
public class Sender(IPublishEndpoint publishEndpoint)
{
    public async Task Go()
    {
        object msg = new OrderSubmitted();
        await publishEndpoint.Publish(msg);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Sender.cs": source})

        channels = [e.identity["channel_address"] for e in build.entities if e.kind == "EventChannel"]
        self.assertEqual(channels, ["OrderSubmitted"])
        self.assertNotIn("object", channels)

    def test_unresolvable_producer_message_emits_coverage_not_a_guess(self) -> None:
        # Publishing a parameter whose concrete type is not statically visible -> loud refusal.
        source = """using MassTransit;
namespace App;
public class Svc(IPublishEndpoint publishEndpoint)
{
    public async Task Go(object evt)
    {
        await publishEndpoint.Publish(evt);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Svc.cs": source})

        self.assertEqual([f for f in build.facts if f.predicate == "PRODUCES_EVENT"], [])
        unresolved = [
            c for c in build.coverage
            if c.scope_ref.get("reason") == "unresolved_event_message_type"
        ]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].state, "partially_instrumented")


    def test_namespace_qualified_publish_receiver_is_recognized(self) -> None:
        # A fully-qualified receiver type (e.g. MassTransit.IPublishEndpoint) must still match.
        source = """using MassTransit;
namespace App;
public class Sender
{
    private readonly MassTransit.IPublishEndpoint _publish;
    public async Task Go()
    {
        var msg = new OrderSubmitted();
        await _publish.Publish(msg);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Sender.cs": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(len(produces), 1)
        self.assertEqual(produces[0].qualifier["broker_kind"], "masstransit")

    def test_masstransit_subnamespace_import_satisfies_the_gate(self) -> None:
        # `using MassTransit.Saga;` (sub-namespace) still marks the file as MassTransit.
        source = """using MassTransit.Saga;
namespace App;
public class OrderConsumer : MassTransit.IConsumer<OrderSubmitted>
{
    public Task Consume(MassTransit.ConsumeContext<OrderSubmitted> context) => Task.CompletedTask;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"OrderConsumer.cs": source})

        consumes = [f for f in build.facts if f.predicate == "CONSUMES_EVENT"]
        self.assertEqual(len(consumes), 1)

    def test_namespace_qualified_generic_consumer_base_is_recognized(self) -> None:
        # `: MassTransit.IConsumer<T>` (qualified generic base) must still yield the message type.
        source = """using MassTransit;
namespace App;
public class OrderConsumer : MassTransit.IConsumer<OrderSubmitted>
{
    public Task Consume(ConsumeContext<OrderSubmitted> context) => Task.CompletedTask;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"OrderConsumer.cs": source})

        consumes = [f for f in build.facts if f.predicate == "CONSUMES_EVENT"]
        self.assertEqual(len(consumes), 1)
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["channel_address"], "OrderSubmitted")

    def test_this_qualified_publish_receiver_is_recognized(self) -> None:
        # `this._publish.Publish(...)` must resolve the same as `_publish.Publish(...)`.
        source = """using MassTransit;
namespace App;
public class Sender
{
    private readonly IPublishEndpoint _publish;
    public async Task Go()
    {
        var msg = new OrderSubmitted();
        await this._publish.Publish(msg);
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Sender.cs": source})

        produces = [f for f in build.facts if f.predicate == "PRODUCES_EVENT"]
        self.assertEqual(len(produces), 1)
        channel = next(e for e in build.entities if e.kind == "EventChannel")
        self.assertEqual(channel.identity["channel_address"], "OrderSubmitted")

    def test_calls_inside_field_initializers_are_still_collected(self) -> None:
        # Collecting field bindings must not stop the parser walk from seeing field-initializer
        # calls (CALLS facts only materialize when the callee resolves, so assert at parse level).
        import tree_sitter
        import tree_sitter_c_sharp as tscs

        from source.kg.languages.dotnet.extractors.parser_bridge import _walk_tree

        source = b"""namespace App;
public class Widget
{
    private readonly Thing _thing = Factory.Create();
    public void M() { Helper.Run(); }
}
"""
        parser = tree_sitter.Parser(tree_sitter.Language(tscs.language()))
        parsed = _walk_tree(parser.parse(source).root_node, source)
        call_names = {c.get("name") for c in parsed["calls"]}
        self.assertIn("Factory.Create", call_names)
        self.assertIn("Helper.Run", call_names)


if __name__ == "__main__":
    unittest.main()
