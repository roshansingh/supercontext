from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from source.kg.core.models import Coverage, Entity, EvidenceDerivationClass, JsonObject
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
    bind_args,
    body_call_nodes,
    import_bindings,
    local_literal_assignments,
    resolved_to_json,
    unresolved_coverage,
)
from source.kg.extraction.python.transport_apis import supported_transports, transport_spec
from source.kg.normalization.python.imports import NormalizedImport


MAX_WRAPPER_RESOLUTION_DEPTH = 2
FunctionDefNode = ast.FunctionDef | ast.AsyncFunctionDef


class CallerSymbol(Protocol):
    entity: Entity
    module_name: str
    line: int


class KgBuildLike(Protocol):
    coverage: list[Coverage]


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
    caller: CallerSymbol,
    caller_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: list[NormalizedImport],
    literal_index: LiteralIndex,
    build: KgBuildLike,
    source_system: str,
    add_entity_evidence: Callable[..., None],
    add_fact: Callable[..., None],
    function_defs: dict[str, FunctionDefNode] | None = None,
) -> None:
    boto3_names = _boto3_names(imports)
    resolver = _resolver(caller.module_name, literal_index, imports, caller_node)
    clients = _transport_clients(caller_node, boto3_names)
    queue_resources = _queue_resources(caller_node, clients, boto3_names)
    for call_node in body_call_nodes(caller_node):
        event = _event_from_call(call_node, clients, queue_resources, boto3_names, resolver)
        if event is None and function_defs:
            event = _event_from_wrapper_call(
                call_node,
                function_defs,
                imports,
                literal_index,
                caller.module_name,
                boto3_names,
                resolver,
                caller_node,
                depth=0,
                seen=(),
            )
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
                "source_kind": event.source_kind,
                "api": event.api,
                "broker_kind": event.channel.broker_kind,
                "channel_address": event.channel.channel_address,
                "normalized_channel": event.channel.channel_address,
                "raw_literal": event.channel.properties.get("raw_literal"),
                "resolution": resolved_to_json(event.resolved),
                **event.qualifier,
            },
            derivation_class=event.derivation_class,
        )


@dataclass(frozen=True)
class TransportEvent:
    api: str
    channel: NormalizedChannel | UnresolvedValue
    resolved: ResolvedValue
    source_kind: str = "python_transport_api_call"
    derivation_class: EvidenceDerivationClass = "deterministic_static"
    qualifier: JsonObject | None = None

    def __post_init__(self) -> None:
        if self.qualifier is None:
            object.__setattr__(self, "qualifier", {})


def _transport_clients(function_node: ast.FunctionDef | ast.AsyncFunctionDef, boto3_names: set[str]) -> dict[str, TransportClient]:
    clients: dict[str, TransportClient] = {}
    for value, targets in _assignment_values(function_node):
        client = _transport_client_from_call(value, boto3_names)
        if client is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                clients[target.id] = client
    return clients


def _queue_resources(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    clients: dict[str, TransportClient],
    boto3_names: set[str],
) -> dict[str, QueueResource]:
    queues: dict[str, QueueResource] = {}
    for value, targets in _assignment_values(function_node):
        queue_arg = _queue_arg_from_call(value, clients, boto3_names)
        if queue_arg is None:
            continue
        for target in targets:
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


def _event_from_wrapper_call(
    call_node: ast.Call,
    function_defs: dict[str, FunctionDefNode],
    imports: list[NormalizedImport],
    literal_index: LiteralIndex,
    module_name: str,
    boto3_names: set[str],
    caller_resolver: ValueResolver,
    caller_node: FunctionDefNode,
    *,
    depth: int,
    seen: tuple[str, ...],
) -> TransportEvent | None:
    if depth >= MAX_WRAPPER_RESOLUTION_DEPTH:
        return None
    callee_name = _local_function_name(call_node.func)
    if callee_name is None or callee_name in seen:
        return None
    if callee_name in _local_binding_names(caller_node):
        return None
    wrapper_node = function_defs.get(callee_name)
    if wrapper_node is None:
        return None
    wrapper_resolver = _resolver(
        module_name,
        literal_index,
        imports,
        wrapper_node,
        extra_local_values=_resolved_bindings(call_node, wrapper_node, caller_resolver),
    )
    clients = _transport_clients(wrapper_node, boto3_names)
    queue_resources = _queue_resources(wrapper_node, clients, boto3_names)
    for nested_call in body_call_nodes(wrapper_node):
        event = _event_from_call(nested_call, clients, queue_resources, boto3_names, wrapper_resolver)
        if event is None:
            event = _event_from_wrapper_call(
                nested_call,
                function_defs,
                imports,
                literal_index,
                module_name,
                boto3_names,
                wrapper_resolver,
                wrapper_node,
                depth=depth + 1,
                seen=(*seen, callee_name),
            )
        if event is not None:
            wrapper_depth = event.qualifier.get("wrapper_depth") if event.qualifier else None
            if not isinstance(wrapper_depth, int):
                wrapper_depth = depth + 1
            return TransportEvent(
                api=event.api,
                channel=event.channel,
                resolved=event.resolved,
                source_kind="python_transport_wrapper_call",
                derivation_class="static_inferred",
                qualifier={"wrapper_depth": max(depth + 1, wrapper_depth), "promotion": "local_wrapper_body"},
            )
    return None


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
        return normalize_sqs_url(value) or normalize_sqs_arn(value)
    if transport == "sns":
        return normalize_sns_arn(value)
    return None


def _transport_client_from_call(node: ast.AST, boto3_names: set[str]) -> TransportClient | None:
    if not isinstance(node, ast.Call):
        return None
    call_name = _call_name(node.func)
    if not any(call_name == f"{name}.client" or call_name == f"{name}.resource" for name in boto3_names):
        return None
    transport = _constant_string_arg(node, 0, ("service_name",))
    if transport is None:
        return None
    if transport not in supported_transports():
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
    return _arg_node(node, 0, ("url", "QueueUrl"))


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


def _resolver(
    module_name: str,
    literal_index: LiteralIndex,
    imports: list[NormalizedImport],
    function_node: FunctionDefNode,
    extra_local_values: dict[str, ast.AST] | None = None,
) -> ValueResolver:
    imported_modules, imported_values = import_bindings(imports)
    local_values = _module_values(module_name, literal_index)
    if extra_local_values:
        local_values.update(extra_local_values)
    local_values.update(local_literal_assignments(function_node))
    return ValueResolver(
        ValueScope(
            local_values=local_values,
            imported_modules=imported_modules,
            imported_values=imported_values,
        ),
        literal_index,
    )


def _resolved_bindings(
    call_node: ast.Call,
    function_node: FunctionDefNode,
    caller_resolver: ValueResolver,
) -> dict[str, ast.AST]:
    resolved_bindings: dict[str, ast.AST] = {}
    bindings = bind_args(call_node, function_node)
    if bindings is None:
        return {}
    for name, value_node in bindings.items():
        resolved = caller_resolver.resolve_value(value_node)
        if isinstance(resolved, ResolvedValue):
            resolved_bindings[name] = ast.Constant(value=resolved.value)
        else:
            resolved_bindings[name] = value_node
    return resolved_bindings


def _assignment_values(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[ast.AST, tuple[ast.expr, ...]]]:
    assignments: list[tuple[ast.AST, tuple[ast.expr, ...]]] = []
    for statement in function_node.body:
        if isinstance(statement, ast.Assign):
            assignments.append((statement.value, tuple(statement.targets)))
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            assignments.append((statement.value, (statement.target,)))
    return assignments


def _keyword_arg(call_node: ast.Call, name: str) -> ast.AST | None:
    for keyword in call_node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _arg_node(call_node: ast.Call, position: int, keyword_names: tuple[str, ...]) -> ast.AST | None:
    if len(call_node.args) > position:
        return call_node.args[position]
    for keyword in call_node.keywords:
        if keyword.arg in keyword_names:
            return keyword.value
    return None


def _constant_string_arg(call_node: ast.Call, position: int, keyword_names: tuple[str, ...]) -> str | None:
    node = _arg_node(call_node, position, keyword_names)
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return None
    return node.value


def _receiver(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Attribute):
        return node.value
    return None


def _local_function_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _local_binding_names(function_node: FunctionDefNode) -> set[str]:
    names = {
        arg.arg
        for arg in [
            *function_node.args.posonlyargs,
            *function_node.args.args,
            *function_node.args.kwonlyargs,
        ]
    }
    if function_node.args.vararg is not None:
        names.add(function_node.args.vararg.arg)
    if function_node.args.kwarg is not None:
        names.add(function_node.args.kwarg.arg)
    collector = _BindingCollector()
    for statement in function_node.body:
        collector.visit(statement)
    names.update(collector.names)
    return names


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names.update(_target_names(element))
        return names
    return set()


class _BindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.names.update(_target_names(target))
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.names.update(_target_names(node.target))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.iter)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.iter)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.names.update(_target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.names.update(_target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            self.names.add(alias.asname or alias.name)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arg_defaults(node.args)
        return

    def _visit_arg_defaults(self, args: ast.arguments) -> None:
        for default in [*args.defaults, *[default for default in args.kw_defaults if default is not None]]:
            self.visit(default)


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
