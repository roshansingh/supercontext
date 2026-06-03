"""Deterministic .NET event-transport extraction (PRODUCES_EVENT / CONSUMES_EVENT).

Runs inside the C# bridge extractor so event facts attach to the same CodeSymbol entities
the rest of the .NET KG already builds. Operates on the parsed-JSON output of
``parser_bridge`` (base lists, invocation generic args, receiver/argument shapes, and
parameter/field/local type bindings) — never on raw text.

Covered ecosystems:

* **MassTransit** — consumers declare ``: IConsumer<TMessage>`` (gated on a ``using
  MassTransit`` so an unrelated ``IConsumer<T>`` stays out); producers call
  ``IPublishEndpoint/IBus.Publish`` or ``ISendEndpoint.Send``.
* **Integration-event bus** (eShop style) — consumers declare
  ``: IIntegrationEventHandler<TMessage>``; producers call ``IEventBus.Publish/PublishAsync``.

The event channel is the message TYPE (these brokers route by message type, not a named
queue). ``Publish``/``Send`` collide with MediatR (``ISender.Send`` / ``IMediator.Publish``),
so producers are recognised only when the receiver's declared type resolves to a known
publish interface — never by method name alone. When the published message type is not
statically resolvable, a loud-refusal ``coverage`` row is emitted instead of a guess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import event_channel_entity


# Consumer interface -> (broker_kind, required import root or None for ungated).
_CONSUMER_INTERFACES: dict[str, tuple[str, str | None]] = {
    "IConsumer": ("masstransit", "MassTransit"),
    "IIntegrationEventHandler": ("integration_event", None),
}

# Publish receiver interface -> (broker_kind, allowed publish method names).
_PUBLISH_RECEIVERS: dict[str, tuple[str, frozenset[str]]] = {
    "IPublishEndpoint": ("masstransit", frozenset({"Publish"})),
    "IBus": ("masstransit", frozenset({"Publish"})),
    "ISendEndpoint": ("masstransit", frozenset({"Send"})),
    "IEventBus": ("integration_event", frozenset({"Publish", "PublishAsync"})),
}

_PROMOTION_SOURCE_SYSTEM = "dotnet_event_transport"


def extract_dotnet_events(
    *,
    repo: RepoSnapshot,
    file_path: Path,
    parsed_file: JsonObject,
    symbols_by_qualname: dict[str, list[Entity]],
    build: object,
    tenant_id: str,
    add_fact: Callable[..., None],
    entity_evidence: Callable[..., object],
) -> None:
    import_roots = {
        str(imp.get("raw_target", "")).strip()
        for imp in parsed_file.get("imports", [])
        if str(imp.get("raw_target", "")).strip()
    }
    _extract_consumers(
        repo=repo,
        file_path=file_path,
        parsed_file=parsed_file,
        import_roots=import_roots,
        symbols_by_qualname=symbols_by_qualname,
        build=build,
        tenant_id=tenant_id,
        add_fact=add_fact,
        entity_evidence=entity_evidence,
    )
    _extract_producers(
        repo=repo,
        file_path=file_path,
        parsed_file=parsed_file,
        symbols_by_qualname=symbols_by_qualname,
        build=build,
        tenant_id=tenant_id,
        add_fact=add_fact,
        entity_evidence=entity_evidence,
    )


def _extract_consumers(
    *,
    repo: RepoSnapshot,
    file_path: Path,
    parsed_file: JsonObject,
    import_roots: set[str],
    symbols_by_qualname: dict[str, list[Entity]],
    build: object,
    tenant_id: str,
    add_fact: Callable[..., None],
    entity_evidence: Callable[..., object],
) -> None:
    for symbol in parsed_file.get("symbols", []):
        if symbol.get("kind") not in {"class", "record"}:
            continue
        qualname = str(symbol.get("name", "")).strip()
        if not qualname:
            continue
        for base in symbol.get("bases", []):
            spec = _CONSUMER_INTERFACES.get(_simple_name(str(base.get("name", ""))))
            if spec is None:
                continue
            broker_kind, required_import = spec
            if required_import is not None and not _imports_namespace(import_roots, required_import):
                continue
            type_args = base.get("type_args") or []
            if not type_args:
                continue
            channel_address = str(type_args[0]).strip()
            subject = _first(symbols_by_qualname.get(qualname))
            if not channel_address or subject is None:
                continue
            line = int(symbol.get("line") or 1)
            end_line = int(symbol.get("end_line") or line)
            _emit_event(
                repo=repo,
                file_path=file_path,
                predicate="CONSUMES_EVENT",
                subject=subject,
                broker_kind=broker_kind,
                channel_address=channel_address,
                line=line,
                end_line=end_line,
                source_kind="dotnet_consumer_interface",
                api=f"{base.get('name')}<{channel_address}>",
                build=build,
                tenant_id=tenant_id,
                add_fact=add_fact,
                entity_evidence=entity_evidence,
            )


def _extract_producers(
    *,
    repo: RepoSnapshot,
    file_path: Path,
    parsed_file: JsonObject,
    symbols_by_qualname: dict[str, list[Entity]],
    build: object,
    tenant_id: str,
    add_fact: Callable[..., None],
    entity_evidence: Callable[..., object],
) -> None:
    bindings = {
        (str(b.get("scope", "")), str(b.get("name", ""))): str(b.get("type", ""))
        for b in parsed_file.get("bindings", [])
    }
    locals_index = {
        (str(a.get("scope", "")), str(a.get("name", ""))): str(a.get("type", ""))
        for a in parsed_file.get("local_assignments", [])
    }
    for call in parsed_file.get("calls", []):
        method = str(call.get("method", "")).strip()
        receiver = str(call.get("receiver", "")).strip()
        caller = str(call.get("caller", "")).strip()
        if not method or not receiver or not caller:
            continue
        receiver_type = _resolve_binding_type(bindings, caller, receiver)
        spec = _PUBLISH_RECEIVERS.get(_simple_name(receiver_type)) if receiver_type else None
        if spec is None:
            continue
        broker_kind, methods = spec
        if method not in methods:
            continue
        subject = _first(symbols_by_qualname.get(caller))
        if subject is None:
            continue
        line = int(call.get("line") or 1)
        channel_address = _resolve_message_type(call, caller, locals_index)
        if not channel_address:
            build.coverage.append(  # type: ignore[attr-defined]
                Coverage(
                    tenant_id=tenant_id,
                    predicate="PRODUCES_EVENT",
                    scope_ref={
                        "repo": repo.name,
                        "file_path": _relative(repo, file_path),
                        "reason": "unresolved_event_message_type",
                        "broker_kind": broker_kind,
                        "receiver_type": receiver_type,
                        "method": method,
                        "line": line,
                    },
                    state="partially_instrumented",
                    source_system=_PROMOTION_SOURCE_SYSTEM,
                )
            )
            continue
        _emit_event(
            repo=repo,
            file_path=file_path,
            predicate="PRODUCES_EVENT",
            subject=subject,
            broker_kind=broker_kind,
            channel_address=channel_address,
            line=line,
            end_line=line,
            source_kind="dotnet_publish_call",
            api=f"{receiver_type}.{method}",
            build=build,
            tenant_id=tenant_id,
            add_fact=add_fact,
            entity_evidence=entity_evidence,
        )


def _resolve_binding_type(bindings: dict[tuple[str, str], str], caller: str, receiver: str) -> str | None:
    scope = caller
    while scope:
        found = bindings.get((scope, receiver))
        if found:
            return found
        if "." not in scope:
            break
        scope = scope.rsplit(".", 1)[0]
    return None


def _resolve_message_type(call: JsonObject, caller: str, locals_index: dict[tuple[str, str], str]) -> str | None:
    type_args = call.get("type_args") or []
    if type_args:
        return str(type_args[0]).strip() or None
    first_arg = call.get("first_arg") or {}
    kind = first_arg.get("kind")
    if kind == "object_creation":
        created = first_arg.get("type")
        return str(created).strip() if created else None
    if kind == "identifier":
        resolved = locals_index.get((caller, str(first_arg.get("name", ""))))
        return resolved or None
    return None


def _emit_event(
    *,
    repo: RepoSnapshot,
    file_path: Path,
    predicate: str,
    subject: Entity,
    broker_kind: str,
    channel_address: str,
    line: int,
    end_line: int,
    source_kind: str,
    api: str,
    build: object,
    tenant_id: str,
    add_fact: Callable[..., None],
    entity_evidence: Callable[..., object],
) -> None:
    channel = event_channel_entity(
        repo,
        broker_kind,
        channel_address,
        tenant_id=tenant_id,
        properties={"message_type": channel_address},
    )
    build.entities.append(channel)  # type: ignore[attr-defined]
    build.evidence.append(entity_evidence(repo, channel, file_path, line, line))  # type: ignore[attr-defined]
    add_fact(
        build,
        predicate,
        subject,
        channel,
        repo,
        file_path,
        line,
        end_line,
        qualifier={
            "source_kind": source_kind,
            "api": api,
            "broker_kind": broker_kind,
            "channel_address": channel_address,
            "normalized_channel": channel_address,
        },
    )


def _relative(repo: RepoSnapshot, file_path: Path) -> str:
    try:
        return str(file_path.relative_to(repo.root))
    except ValueError:
        return str(file_path)


def _imports_namespace(import_roots: set[str], required: str) -> bool:
    """True if the file imports the required namespace or any of its sub-namespaces.

    A file that imports e.g. ``MassTransit.Saga`` is still a MassTransit file, so the gate
    matches the namespace prefix rather than requiring the exact root ``using``.
    """
    return any(root == required or root.startswith(required + ".") for root in import_roots)


def _simple_name(type_name: str) -> str:
    """Reduce a type reference to its bare interface name for matching.

    Strips any generic suffix and namespace qualifier so ``MassTransit.IConsumer<T>`` and
    ``global::MassTransit.IPublishEndpoint`` resolve to ``IConsumer`` / ``IPublishEndpoint``.
    """
    without_generics = type_name.split("<", 1)[0]
    return without_generics.rsplit(".", 1)[-1].strip()


def _first(entities: list[Entity] | None) -> Entity | None:
    if not entities:
        return None
    return entities[0]
