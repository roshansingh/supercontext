from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TransportKind = Literal["sqs", "sns"]
ClientFactory = Literal["client", "resource"]
TransportPredicate = Literal["PRODUCES_EVENT", "CONSUMES_EVENT"]


@dataclass(frozen=True)
class TransportApiSpec:
    transport: TransportKind
    factory: ClientFactory
    method: str
    channel_arg: str | None
    predicate: TransportPredicate


TRANSPORT_APIS: tuple[TransportApiSpec, ...] = (
    TransportApiSpec(transport="sqs", factory="client", method="send_message", channel_arg="QueueUrl", predicate="PRODUCES_EVENT"),
    TransportApiSpec(transport="sqs", factory="client", method="send_message_batch", channel_arg="QueueUrl", predicate="PRODUCES_EVENT"),
    TransportApiSpec(transport="sqs", factory="client", method="receive_message", channel_arg="QueueUrl", predicate="CONSUMES_EVENT"),
    TransportApiSpec(transport="sqs", factory="resource", method="send_message", channel_arg=None, predicate="PRODUCES_EVENT"),
    TransportApiSpec(transport="sqs", factory="resource", method="receive_messages", channel_arg=None, predicate="CONSUMES_EVENT"),
    TransportApiSpec(transport="sns", factory="client", method="publish", channel_arg="TopicArn", predicate="PRODUCES_EVENT"),
)


def transport_spec(transport: str, factory: str, method: str) -> TransportApiSpec | None:
    for spec in TRANSPORT_APIS:
        if spec.transport == transport and spec.factory == factory and spec.method == method:
            return spec
    return None


def supported_transports() -> set[str]:
    return {spec.transport for spec in TRANSPORT_APIS}
