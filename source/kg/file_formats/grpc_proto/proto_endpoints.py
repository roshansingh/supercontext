"""Surface gRPC service methods declared in ``.proto`` files as endpoints.

Each ``rpc`` in a ``service`` block is the authoritative wire contract for a
gRPC endpoint, addressed at ``/<package>.<Service>/<Method>``. We emit one
EXPOSES_ENDPOINT fact per rpc on the repo's Service entity, and a loud-refusal
coverage row for any rpc whose signature could not be parsed (never guessed).

A ``service`` declaration is treated as EXPOSES regardless of whether the repo
generates the server or only a client stub: that distinction lives in build
wiring outside the proto (e.g. .NET ``<Protobuf GrpcServices="Client">``) and is
language-specific. Client-side CALLS_ENDPOINT for gRPC is a separate slice.
"""

from __future__ import annotations

from source.kg.core.models import Coverage, Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    grpc_endpoint_entity,
)
from source.kg.file_formats.grpc_proto.proto_service_parser import (
    ProtoService,
    RpcMethod,
    parse_proto_services,
)

_PROTO_SUFFIX = ".proto"
_SOURCE_KIND = "grpc_proto_service"


def extract_grpc_proto_endpoints(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    for scanned in files:
        if scanned.path.suffix != _PROTO_SUFFIX:
            continue
        parsed = parse_proto_services(scanned.text)
        for proto_service in parsed.services:
            for rpc in proto_service.rpcs:
                _emit_grpc_endpoint(
                    repo, scanned, service_entity, build, resolved_tenant_id, proto_service, rpc
                )
        for line in parsed.unparsed_rpc_lines:
            build.coverage.append(
                Coverage(
                    tenant_id=resolved_tenant_id,
                    predicate="EXPOSES_ENDPOINT",
                    scope_ref={
                        "repo": repo.name,
                        "path": scanned.relative_path,
                        "line": line,
                        "language": "protobuf",
                        "reason": "unparsed_grpc_rpc",
                    },
                    state="partially_instrumented",
                    source_system=CONFIG_SOURCE_SYSTEM,
                )
            )


def _emit_grpc_endpoint(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
    proto_service: ProtoService,
    rpc: RpcMethod,
) -> None:
    qualified_service = (
        f"{proto_service.package}.{proto_service.name}"
        if proto_service.package
        else proto_service.name
    )
    grpc_path = f"/{qualified_service}/{rpc.name}"
    properties = {
        "grpc_service": qualified_service,
        "rpc_method": rpc.name,
        "request_type": rpc.request_type,
        "response_type": rpc.response_type,
        "client_streaming": rpc.client_streaming,
        "server_streaming": rpc.server_streaming,
    }
    endpoint = grpc_endpoint_entity(repo, grpc_path, tenant_id=tenant_id, properties=properties)
    add_entity_evidence(build, repo, endpoint, scanned.path, rpc.line)
    add_fact(
        build,
        "EXPOSES_ENDPOINT",
        service_entity,
        endpoint,
        repo,
        scanned.path,
        rpc.line,
        qualifier={
            "source_kind": _SOURCE_KIND,
            "raw_target": grpc_path,
            "path": scanned.relative_path,
            "protocol": "grpc",
            "grpc_service": qualified_service,
            "rpc_method": rpc.name,
            "request_type": rpc.request_type,
            "response_type": rpc.response_type,
            "client_streaming": rpc.client_streaming,
            "server_streaming": rpc.server_streaming,
        },
    )
