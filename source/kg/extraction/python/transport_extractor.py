from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from source.kg.core.models import Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.channel_normalization import (
    NormalizedChannel,
    normalize_sns_arn,
    normalize_sqs_arn,
    normalize_sqs_url,
)
from source.kg.extraction.config.common import event_channel_entity
from source.kg.extraction.python.dataflow import (
    LiteralIndex,
    ResolvedValue,
    UnresolvedValue,
    ValueResolver,
    ValueScope,
    import_bindings,
    local_literal_assignments,
    resolved_to_json,
    unresolved_coverage,
)
from source.kg.extraction.python.transport_apis import transport_spec
from source.kg.normalization.python.imports import NormalizedImport


@dataclass(frozen=True)
class TransportClient:
    transport: str
    factory: str


@dataclass(frozen=True)
class QueueResource:
    channel_arg: ast.AST


def extract_transport_events(
    repo: RepoSnapshot,
    file_path: Path,
    caller: Any,
    caller_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: list[NormalizedImport],
    literal_index: LiteralIndex,
    build: Any,
    source_system: str,
    add_entity_evidence,
    add_fact,
) -> None:
    boto3_names = _boto3_names(imports)
    imported_modules, imported_values = import_bindings(imports)
    local_values = _module_values(caller.module_name, literal_index)
    local_values.update(local_literal_assignments(caller_node))
    resolver = ValueResolver(
        ValueScope(
            local_values=local_values,
            imported_modules=imported_modules,
            imported_values=imported_values,
        ),
        literal_index,
    )
    clients = _transport_clients(caller_node, boto3_names)
    queue_resources = _queue_resources(caller_node, clients, boto3_names)
    for call_node in [node for node in ast.walk(caller_node) if isinstance(node, ast.Call)]:
        event = _event_from_call(call_node, clients, queue_resources, boto3_names, resolver)
        if event is None:
            continue
        line = getattr(call_node, "lineno", caller.line)
        if isinstance(event.channel, UnresolvedValue):
            build.coverage.append(
                unresolved_coverage(repo, file_path, event.channel, source_system, predicate="PRODUCES_EVENT", line=line)
            )
            continue
        channel = event_channel_entity(
            repo,
            event.channel.broker_kind,
            event.channel.channel_address,
            properties=event.channel.properties,
        )
        add_entity_evidence(build, repo, channel, file_path, line, line)
        add_fact(
            build,
            "PRODUCES_EVENT",
            caller.entity,
            channel,
            repo,
            file_path,
            line,
            line,
            qualifier={
                "source_kind": "python_transport_api_call",
                "api": event.api,
                "broker_kind": event.channel.broker_kind,
                "channel_address": event.channel.channel_address,
                "normalized_channel": event.channel.channel_address,
                "raw_literal": event.channel.properties.get("raw_literal"),
                "resolution": resolved_to_json(event.resolved),
            },
            derivation_class="deterministic_static",
        )


@dataclass(frozen=True)
class TransportEvent:
    api: str
    channel: NormalizedChannel | UnresolvedValue
    resolved: ResolvedValue


def _transport_clients(function_node: ast.FunctionDef | ast.AsyncFunctionDef, boto3_names: set[str]) -> dict[str, TransportClient]:
    clients: dict[str, TransportClient] = {}
    for statement in function_node.body:
        if not isinstance(statement, ast.Assign):
            continue
        client = _transport_client_from_call(statement.value, boto3_names)
        if client is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                clients[target.id] = client
    return clients


def _queue_resources(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    clients: dict[str, TransportClient],
    boto3_names: set[str],
) -> dict[str, QueueResource]:
    queues: dict[str, QueueResource] = {}
    for statement in function_node.body:
        if not isinstance(statement, ast.Assign):
            continue
        queue_arg = _queue_arg_from_call(statement.value, clients, boto3_names)
        if queue_arg is None:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                queues[target.id] = QueueResource(channel_arg=queue_arg)
    return queues


def _event_from_call(
    call_node: ast.Call,
    clients: dict[str, TransportClient],
    queue_resources: dict[str, QueueResource],
    boto3_names: set[str],
    resolver: ValueResolver,
) -> TransportEvent | None:
    method = _method_name(call_node.func)
    if method is None:
        return None

    receiver = _receiver(call_node.func)
    if receiver is None:
        return None

    queue_arg = _queue_arg_from_receiver(receiver, clients, queue_resources, boto3_names)
    if queue_arg is not None:
        spec = transport_spec("sqs", "resource", method)
        if spec is None:
            return None
        return _event_from_channel_arg(f"boto3.resource('sqs').Queue(...).{method}", "sqs", queue_arg, resolver)

    client = _client_from_receiver(receiver, clients, boto3_names)
    if client is None:
        return None
    spec = transport_spec(client.transport, client.factory, method)
    if spec is None or spec.channel_arg is None:
        return None
    channel_arg = _keyword_arg(call_node, spec.channel_arg)
    if channel_arg is None:
        return None
    return _event_from_channel_arg(f"boto3.{client.factory}('{client.transport}').{method}", client.transport, channel_arg, resolver)


def _event_from_channel_arg(
    api: str,
    transport: str,
    channel_arg: ast.AST,
    resolver: ValueResolver,
) -> TransportEvent | None:
    resolved = resolver.resolve_value(channel_arg)
    if isinstance(resolved, UnresolvedValue):
        return TransportEvent(api=api, channel=resolved, resolved=ResolvedValue(None, "unresolved", resolved.expression))
    if not isinstance(resolved.value, str):
        return TransportEvent(
            api=api,
            channel=UnresolvedValue("non_string_channel", resolved.expression),
            resolved=resolved,
        )
    channel = _normalize_channel(transport, resolved.value)
    if channel is None:
        return TransportEvent(
            api=api,
            channel=UnresolvedValue("unsupported_channel_literal", resolved.expression),
            resolved=resolved,
        )
    return TransportEvent(api=api, channel=channel, resolved=resolved)


def _normalize_channel(transport: str, value: str) -> NormalizedChannel | None:
    if transport == "sqs":
        return normalize_sqs_url(value) or normalize_sqs_arn(value) or _plain_channel("sqs", value, "queue_name")
    if transport == "sns":
        return normalize_sns_arn(value) or _plain_channel("sns", value, "topic_name")
    return None


def _plain_channel(broker_kind: str, value: str, property_name: str) -> NormalizedChannel | None:
    channel_address = value.strip()
    if not channel_address:
        return None
    return NormalizedChannel(
        broker_kind=broker_kind,
        channel_address=channel_address,
        properties={"raw_literal": value, property_name: channel_address},
    )


def _transport_client_from_call(node: ast.AST, boto3_names: set[str]) -> TransportClient | None:
    if not isinstance(node, ast.Call):
        return None
    call_name = _call_name(node.func)
    if not any(call_name == f"{name}.client" or call_name == f"{name}.resource" for name in boto3_names):
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    transport = node.args[0].value
    if transport not in {"sqs", "sns"}:
        return None
    factory = _method_name(node.func)
    if factory not in {"client", "resource"}:
        return None
    return TransportClient(transport=transport, factory=factory)


def _queue_arg_from_call(node: ast.AST, clients: dict[str, TransportClient], boto3_names: set[str]) -> ast.AST | None:
    if not isinstance(node, ast.Call) or _method_name(node.func) != "Queue":
        return None
    receiver = _receiver(node.func)
    if receiver is None:
        return None
    client = _client_from_receiver(receiver, clients, boto3_names)
    if client is None or client.transport != "sqs" or client.factory != "resource":
        return None
    return node.args[0] if node.args else None


def _queue_arg_from_receiver(
    receiver: ast.AST,
    clients: dict[str, TransportClient],
    queue_resources: dict[str, QueueResource],
    boto3_names: set[str],
) -> ast.AST | None:
    if isinstance(receiver, ast.Name):
        queue = queue_resources.get(receiver.id)
        return queue.channel_arg if queue is not None else None
    return _queue_arg_from_call(receiver, clients, boto3_names)


def _client_from_receiver(receiver: ast.AST, clients: dict[str, TransportClient], boto3_names: set[str]) -> TransportClient | None:
    if isinstance(receiver, ast.Name):
        return clients.get(receiver.id)
    return _transport_client_from_call(receiver, boto3_names)


def _boto3_names(imports: list[NormalizedImport]) -> set[str]:
    names = set()
    for import_ref in imports:
        if import_ref.import_root == "boto3" and not import_ref.imported_names:
            names.add(import_ref.alias or "boto3")
    return names


def _module_values(module_name: str, literal_index: LiteralIndex) -> dict[str, ast.AST]:
    return {ref.name: node for ref, node in literal_index.values.items() if ref.module_name == module_name}


def _keyword_arg(call_node: ast.Call, name: str) -> ast.AST | None:
    for keyword in call_node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _receiver(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Attribute):
        return node.value
    return None


def _method_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""
