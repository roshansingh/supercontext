from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from source.kg.core.models import Coverage, Entity, EvidenceDerivationClass, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.file_formats.channel_normalization import (
    NormalizedChannel,
    normalize_sns_arn,
    normalize_sqs_arn,
    normalize_sqs_queue_name,
    normalize_sqs_url,
)
from source.kg.extraction.file_formats.common import event_channel_entity
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
    local_literal_assignments_before,
    node_starts_before,
    resolved_to_json,
    unresolved_coverage,
)
from source.kg.extraction.python.transport_apis import supported_transports, transport_spec
from source.kg.normalization.python.imports import NormalizedImport


MAX_WRAPPER_RESOLUTION_DEPTH = 2
FunctionDefNode = ast.FunctionDef | ast.AsyncFunctionDef
BindingNameCache = dict[int, set[str]]
CallNodeCache = dict[int, list[ast.Call]]


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
    channel_arg_kind: str


@dataclass(frozen=True)
class ModuleTransportContext:
    clients: dict[str, TransportClient]
    queue_resources: dict[str, QueueResource]


def module_transport_context(module_node: ast.Module | None, imports: list[NormalizedImport]) -> ModuleTransportContext:
    if module_node is None:
        return ModuleTransportContext(clients={}, queue_resources={})
    boto3_names = _boto3_names(imports)
    clients = _module_transport_clients(module_node, boto3_names)
    queue_resources = _module_queue_resources(module_node, clients, boto3_names)
    return ModuleTransportContext(clients=clients, queue_resources=queue_resources)


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
    module_node: ast.Module | None = None,
    module_context: ModuleTransportContext | None = None,
    *,
    tenant_id: str,
) -> None:
    boto3_names = _boto3_names(imports)
    binding_name_cache: BindingNameCache = {}
    call_node_cache: CallNodeCache = {}
    caller_binding_names = _local_binding_names_cached(caller_node, binding_name_cache)
    if module_context is None:
        module_context = module_transport_context(module_node, imports)
    module_clients = module_context.clients
    module_queue_resources = module_context.queue_resources
    for call_node in _body_call_nodes_cached(caller_node, call_node_cache):
        resolver = _resolver(
            caller.module_name,
            literal_index,
            imports,
            caller_node,
            before_node=call_node,
            local_binding_names=caller_binding_names,
        )
        clients = {**module_clients, **_transport_clients(caller_node, boto3_names, before_node=call_node)}
        queue_resources = {
            **module_queue_resources,
            **_queue_resources(caller_node, clients, boto3_names, before_node=call_node),
        }
        events = _events_from_call(call_node, clients, queue_resources, boto3_names, resolver)
        if not events and function_defs:
            events = _events_from_wrapper_call(
                call_node,
                function_defs,
                imports,
                literal_index,
                caller.module_name,
                boto3_names,
                resolver,
                caller_node,
                binding_name_cache,
                call_node_cache,
                depth=0,
                seen=(),
            )
        if not events:
            continue
        line = getattr(call_node, "lineno", caller.line)
        for event in events:
            if isinstance(event.channel, UnresolvedValue):
                build.coverage.append(
                    unresolved_coverage(
                        repo,
                        file_path,
                        event.channel,
                        source_system,
                        predicate=event.predicate,
                        line=line,
                        tenant_id=tenant_id,
                    )
                )
                continue
            channel = event_channel_entity(
                repo,
                event.channel.broker_kind,
                event.channel.channel_address,
                tenant_id=tenant_id,
                properties=event.channel.properties,
            )
            add_entity_evidence(build, repo, channel, file_path, line, line)
            add_fact(
                build,
                event.predicate,
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
    predicate: str
    api: str
    channel: NormalizedChannel | UnresolvedValue
    resolved: ResolvedValue
    source_kind: str = "python_transport_api_call"
    derivation_class: EvidenceDerivationClass = "deterministic_static"
    qualifier: JsonObject | None = None

    def __post_init__(self) -> None:
        if self.qualifier is None:
            object.__setattr__(self, "qualifier", {})


def _transport_clients(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    boto3_names: set[str],
    before_node: ast.AST | None = None,
) -> dict[str, TransportClient]:
    clients: dict[str, TransportClient] = {}
    for value, targets in _assignment_values(function_node, before_node=before_node):
        client = _transport_client_from_call(value, boto3_names)
        if client is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                clients[target.id] = client
    return clients


def _module_transport_clients(
    module_node: ast.Module,
    boto3_names: set[str],
) -> dict[str, TransportClient]:
    clients: dict[str, TransportClient] = {}
    for value, targets in _module_assignment_values(module_node):
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
    before_node: ast.AST | None = None,
) -> dict[str, QueueResource]:
    queues_by_name: dict[str, list[QueueResource]] = {}
    for value, targets in _assignment_values(function_node, before_node=before_node):
        queue_arg = _queue_resource_from_call(value, clients, boto3_names)
        if queue_arg is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                queues_by_name.setdefault(target.id, []).append(queue_arg)
    return {name: queues[0] for name, queues in queues_by_name.items() if len(queues) == 1}


def _module_queue_resources(
    module_node: ast.Module,
    clients: dict[str, TransportClient],
    boto3_names: set[str],
) -> dict[str, QueueResource]:
    queues_by_name: dict[str, list[QueueResource]] = {}
    for value, targets in _module_assignment_values(module_node):
        queue_arg = _queue_resource_from_call(value, clients, boto3_names)
        if queue_arg is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                queues_by_name.setdefault(target.id, []).append(queue_arg)
    return {name: queues[0] for name, queues in queues_by_name.items() if len(queues) == 1}


def _events_from_call(
    call_node: ast.Call,
    clients: dict[str, TransportClient],
    queue_resources: dict[str, QueueResource],
    boto3_names: set[str],
    resolver: ValueResolver,
) -> list[TransportEvent]:
    method = _method_name(call_node.func)
    if method is None:
        return []

    receiver = _receiver(call_node.func)
    if receiver is None:
        return []

    queue_resource = _queue_resource_from_receiver(receiver, clients, queue_resources, boto3_names)
    if queue_resource is not None:
        spec = transport_spec("sqs", "resource", method)
        if spec is None:
            return []
        return _events_from_channel_arg(
            spec.predicate,
            f"boto3.resource('sqs').Queue(...).{method}",
            "sqs",
            queue_resource.channel_arg,
            resolver,
            allow_bare_sqs_name=queue_resource.channel_arg_kind == "queue_name",
        )

    client = _client_from_receiver(receiver, clients, boto3_names)
    if client is None:
        return []
    spec = transport_spec(client.transport, client.factory, method)
    if spec is None or spec.channel_arg is None:
        return []
    channel_arg = _keyword_arg(call_node, spec.channel_arg)
    if channel_arg is None:
        return []
    return _events_from_channel_arg(
        spec.predicate,
        f"boto3.{client.factory}('{client.transport}').{method}",
        client.transport,
        channel_arg,
        resolver,
        allow_bare_sqs_name=False,
    )


def _events_from_wrapper_call(
    call_node: ast.Call,
    function_defs: dict[str, FunctionDefNode],
    imports: list[NormalizedImport],
    literal_index: LiteralIndex,
    module_name: str,
    boto3_names: set[str],
    caller_resolver: ValueResolver,
    caller_node: FunctionDefNode,
    binding_name_cache: BindingNameCache,
    call_node_cache: CallNodeCache,
    *,
    depth: int,
    seen: tuple[str, ...],
) -> list[TransportEvent]:
    if depth >= MAX_WRAPPER_RESOLUTION_DEPTH:
        return []
    callee_name = _local_function_name(call_node.func)
    if callee_name is None or callee_name in seen:
        return []
    if callee_name in _local_binding_names_cached(caller_node, binding_name_cache):
        return []
    wrapper_node = function_defs.get(callee_name)
    if wrapper_node is None:
        return []
    resolved_bindings = _resolved_bindings(call_node, wrapper_node, caller_resolver)
    if resolved_bindings is None:
        return []
    wrapper_binding_names = _local_binding_names_cached(wrapper_node, binding_name_cache)
    event_groups: list[list[TransportEvent]] = []
    for nested_call in _body_call_nodes_cached(wrapper_node, call_node_cache):
        wrapper_resolver = _resolver(
            module_name,
            literal_index,
            imports,
            wrapper_node,
            extra_resolved_values=resolved_bindings,
            before_node=nested_call,
            local_binding_names=wrapper_binding_names,
        )
        clients = _transport_clients(wrapper_node, boto3_names, before_node=nested_call)
        queue_resources = _queue_resources(wrapper_node, clients, boto3_names, before_node=nested_call)
        events = _events_from_call(nested_call, clients, queue_resources, boto3_names, wrapper_resolver)
        if not events:
            events = _events_from_wrapper_call(
                nested_call,
                function_defs,
                imports,
                literal_index,
                module_name,
                boto3_names,
                wrapper_resolver,
                wrapper_node,
                binding_name_cache,
                call_node_cache,
                depth=depth + 1,
                seen=(*seen, callee_name),
            )
        if events:
            event_groups.append(events)
    if len(event_groups) != 1:
        return []
    wrapped_events = []
    for event in event_groups[0]:
        wrapper_depth = event.qualifier.get("wrapper_depth") if event.qualifier else None
        if not isinstance(wrapper_depth, int):
            wrapper_depth = depth + 1
        wrapped_events.append(
            TransportEvent(
                predicate=event.predicate,
                api=event.api,
                channel=event.channel,
                resolved=event.resolved,
                source_kind="python_transport_wrapper_call",
                derivation_class="static_inferred",
                qualifier={"wrapper_depth": max(depth + 1, wrapper_depth), "promotion": "local_wrapper_body"},
            )
        )
    return wrapped_events


def _events_from_channel_arg(
    predicate: str,
    api: str,
    transport: str,
    channel_arg: ast.AST,
    resolver: ValueResolver,
    *,
    allow_bare_sqs_name: bool,
) -> list[TransportEvent]:
    resolved = resolver.resolve_value(channel_arg)
    if isinstance(resolved, UnresolvedValue):
        return [TransportEvent(predicate=predicate, api=api, channel=resolved, resolved=ResolvedValue(None, "unresolved", resolved.expression))]
    values = _resolved_string_values(resolved.value)
    if values is None:
        return [
            TransportEvent(
                predicate=predicate,
                api=api,
                channel=UnresolvedValue("non_string_channel", resolved.expression),
                resolved=resolved,
            )
        ]
    events = []
    for value in values:
        channel = _normalize_channel(transport, value, allow_bare_sqs_name=allow_bare_sqs_name)
        if channel is None:
            events.append(
                TransportEvent(
                    predicate=predicate,
                    api=api,
                    channel=UnresolvedValue("unsupported_channel_literal", resolved.expression),
                    resolved=resolved,
                )
            )
            continue
        events.append(TransportEvent(predicate=predicate, api=api, channel=channel, resolved=resolved))
    return events


def _normalize_channel(transport: str, value: str, *, allow_bare_sqs_name: bool) -> NormalizedChannel | None:
    if transport == "sqs":
        channel = normalize_sqs_url(value) or normalize_sqs_arn(value)
        if channel is not None:
            return channel
        if allow_bare_sqs_name:
            return normalize_sqs_queue_name(value)
        return None
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


def _queue_resource_from_call(node: ast.AST, clients: dict[str, TransportClient], boto3_names: set[str]) -> QueueResource | None:
    if not isinstance(node, ast.Call):
        return None
    receiver = _receiver(node.func)
    if receiver is None:
        return None
    client = _client_from_receiver(receiver, clients, boto3_names)
    if client is None or client.transport != "sqs" or client.factory != "resource":
        return None
    method = _method_name(node.func)
    if method == "Queue":
        channel_arg = _arg_node(node, 0, ("url", "QueueUrl"))
        return QueueResource(channel_arg=channel_arg, channel_arg_kind="queue_url") if channel_arg is not None else None
    if method == "get_queue_by_name":
        channel_arg = _arg_node(node, 0, ("QueueName", "queue_name"))
        return QueueResource(channel_arg=channel_arg, channel_arg_kind="queue_name") if channel_arg is not None else None
    return None


def _queue_resource_from_receiver(
    receiver: ast.AST,
    clients: dict[str, TransportClient],
    queue_resources: dict[str, QueueResource],
    boto3_names: set[str],
) -> QueueResource | None:
    if isinstance(receiver, ast.Name):
        return queue_resources.get(receiver.id)
    return _queue_resource_from_call(receiver, clients, boto3_names)


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
    extra_resolved_values: dict[str, ResolvedValue] | None = None,
    before_node: ast.AST | None = None,
    local_binding_names: set[str] | None = None,
) -> ValueResolver:
    imported_modules, imported_values = import_bindings(imports)
    local_values = _module_values(module_name, literal_index)
    known_local_names: set[str] = set()
    if extra_resolved_values:
        known_local_names.update(extra_resolved_values)
    if before_node is None:
        local_literals = local_literal_assignments(function_node)
    else:
        local_literals = local_literal_assignments_before(function_node, before_node)
    local_values.update(local_literals)
    known_local_names.update(local_literals)
    blocked_names = set()
    if local_binding_names is not None:
        blocked_names = local_binding_names - known_local_names
    return ValueResolver(
        ValueScope(
            local_values=local_values,
            local_resolved_values=extra_resolved_values or {},
            imported_modules=imported_modules,
            imported_values=imported_values,
            blocked_names=blocked_names,
        ),
        literal_index,
    )


def _resolved_bindings(
    call_node: ast.Call,
    function_node: FunctionDefNode,
    caller_resolver: ValueResolver,
) -> dict[str, ResolvedValue] | None:
    resolved_bindings: dict[str, ResolvedValue] = {}
    bindings = bind_args(call_node, function_node)
    if bindings is None:
        return None
    for name, value_node in bindings.items():
        resolved = caller_resolver.resolve_value(value_node)
        if isinstance(resolved, ResolvedValue):
            resolved_bindings[name] = resolved
        else:
            return None
    return resolved_bindings


def _assignment_values(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    before_node: ast.AST | None = None,
) -> list[tuple[ast.AST, tuple[ast.expr, ...]]]:
    collector = _AssignmentCollector(before_node)
    for statement in function_node.body:
        collector.visit(statement)
    return collector.assignments


def _module_assignment_values(module_node: ast.Module) -> list[tuple[ast.AST, tuple[ast.expr, ...]]]:
    assignments: list[tuple[ast.AST, tuple[ast.expr, ...]]] = []
    for statement in module_node.body:
        if isinstance(statement, ast.Assign):
            assignments.append((statement.value, tuple(statement.targets)))
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            assignments.append((statement.value, (statement.target,)))
    return assignments


def _resolved_string_values(value: object) -> tuple[str, ...] | None:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, set):
        values = []
        for item in value:
            if not isinstance(item, str):
                return None
            values.append(item)
        return tuple(sorted(values))
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            if not isinstance(item, str):
                return None
            values.append(item)
        return tuple(values)
    return None


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


def _body_call_nodes_cached(function_node: FunctionDefNode, cache: CallNodeCache) -> list[ast.Call]:
    key = id(function_node)
    calls = cache.get(key)
    if calls is None:
        calls = body_call_nodes(function_node)
        cache[key] = calls
    return calls


def _local_binding_names_cached(function_node: FunctionDefNode, cache: BindingNameCache) -> set[str]:
    key = id(function_node)
    names = cache.get(key)
    if names is None:
        names = _local_binding_names(function_node)
        cache[key] = names
    return names


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
    names.difference_update(collector.global_names)
    names.update(collector.nonlocal_names)
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


class _AssignmentCollector(ast.NodeVisitor):
    def __init__(self, before_node: ast.AST | None) -> None:
        self.before_node = before_node
        self.assignments: list[tuple[ast.AST, tuple[ast.expr, ...]]] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_before_reference(node):
            self.assignments.append((node.value, tuple(node.targets)))
            self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and self._is_before_reference(node):
            self.assignments.append((node.value, (node.target,)))
            self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def _is_before_reference(self, node: ast.AST) -> bool:
        if self.before_node is None:
            return True
        return node_starts_before(node, self.before_node)


class _BindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocal_names.update(node.names)

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

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            self.names.update(_pattern_names(case.pattern))
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)

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


def _pattern_names(pattern: ast.AST) -> set[str]:
    if isinstance(pattern, ast.MatchAs):
        names = _pattern_names(pattern.pattern) if pattern.pattern is not None else set()
        if pattern.name is not None:
            names.add(pattern.name)
        return names
    if isinstance(pattern, ast.MatchStar):
        return {pattern.name} if pattern.name is not None else set()
    if isinstance(pattern, ast.MatchMapping):
        names = set()
        for child in pattern.patterns:
            names.update(_pattern_names(child))
        if pattern.rest is not None:
            names.add(pattern.rest)
        return names
    if isinstance(pattern, ast.MatchSequence):
        names = set()
        for child in pattern.patterns:
            names.update(_pattern_names(child))
        return names
    if isinstance(pattern, ast.MatchClass):
        names = set()
        for child in [*pattern.patterns, *pattern.kwd_patterns]:
            names.update(_pattern_names(child))
        return names
    if isinstance(pattern, ast.MatchOr):
        names = set()
        for child in pattern.patterns:
            names.update(_pattern_names(child))
        return names
    return set()


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
