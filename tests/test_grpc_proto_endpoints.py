from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.static_config import service_entity_for_repo
from source.kg.file_formats.adapters.config_grpc_proto import CONFIG_GRPC_PROTO_ADAPTER
from source.kg.file_formats.grpc_proto.proto_endpoints import extract_grpc_proto_endpoints
from source.kg.file_formats.grpc_proto.proto_service_parser import parse_proto_services


def _extract(tmp: str, files: dict[str, str]) -> ConfigKgBuild:
    root = Path(tmp)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    repo = discover_repo(root)
    build = ConfigKgBuild()
    service = service_entity_for_repo(repo, "default")
    from source.kg.file_formats._shared.common import scan_config_files

    files_scanned = list(scan_config_files(repo, "default").files)
    extract_grpc_proto_endpoints(repo, files_scanned, service, build, "default")
    return build


def _endpoints(build: ConfigKgBuild) -> list:
    return [e for e in build.entities if e.kind == "Endpoint"]


def _paths(build: ConfigKgBuild) -> set[str]:
    return {e.identity["path"] for e in _endpoints(build)}


_BASKET_PROTO = """syntax = "proto3";

option csharp_namespace = "eShop.Basket.API.Grpc";

package BasketApi;

service Basket {
    rpc GetBasket(GetBasketRequest) returns (CustomerBasketResponse) {}
    rpc UpdateBasket(UpdateBasketRequest) returns (CustomerBasketResponse) {}
    rpc DeleteBasket(DeleteBasketRequest) returns (DeleteBasketResponse) {}
}

message GetBasketRequest {
}
message CustomerBasketResponse {
}
message UpdateBasketRequest {
}
message DeleteBasketRequest {
}
message DeleteBasketResponse {
}
"""


class GrpcProtoEndpointTest(unittest.TestCase):
    def test_service_rpcs_become_grpc_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"Proto/basket.proto": _BASKET_PROTO})

        self.assertEqual(
            _paths(build),
            {
                "/BasketApi.Basket/GetBasket",
                "/BasketApi.Basket/UpdateBasket",
                "/BasketApi.Basket/DeleteBasket",
            },
        )
        # gRPC endpoints are protocol=grpc, addressed over HTTP/2 POST; path is verbatim.
        for endpoint in _endpoints(build):
            self.assertEqual(endpoint.identity["protocol"], "grpc")
            self.assertEqual(endpoint.identity["method"], "POST")
        facts = [f for f in build.facts if f.predicate == "EXPOSES_ENDPOINT"]
        self.assertEqual(len(facts), 3)
        get_basket = next(e for e in _endpoints(build) if e.identity["path"].endswith("/GetBasket"))
        self.assertEqual(get_basket.properties["grpc_service"], "BasketApi.Basket")
        self.assertEqual(get_basket.properties["request_type"], "GetBasketRequest")
        self.assertEqual(get_basket.properties["response_type"], "CustomerBasketResponse")

    def test_facts_and_evidence_carry_bytes_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"basket.proto": _BASKET_PROTO})
        fact_evidence = [e for e in build.evidence if e.target_type == "fact"]
        self.assertTrue(fact_evidence)
        for evidence in fact_evidence:
            self.assertIsNotNone(evidence.bytes_ref)
            self.assertEqual(evidence.bytes_ref["path"], "basket.proto")
            self.assertGreaterEqual(evidence.bytes_ref["line_start"], 8)

    def test_package_optional_path_has_no_leading_dot(self) -> None:
        source = """syntax = "proto3";
service Health {
  rpc Check(HealthCheckRequest) returns (HealthCheckResponse);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"health.proto": source})
        self.assertEqual(_paths(build), {"/Health/Check"})

    def test_streaming_flags_captured(self) -> None:
        source = """syntax = "proto3";
package chat;
service Chat {
  rpc Listen(ListenRequest) returns (stream Event);
  rpc Upload(stream Chunk) returns (UploadResult);
  rpc Both(stream A) returns (stream B);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"chat.proto": source})
        by_method = {e.properties["rpc_method"]: e.properties for e in _endpoints(build)}
        self.assertEqual(
            (by_method["Listen"]["client_streaming"], by_method["Listen"]["server_streaming"]),
            (False, True),
        )
        self.assertEqual(
            (by_method["Upload"]["client_streaming"], by_method["Upload"]["server_streaming"]),
            (True, False),
        )
        self.assertEqual(
            (by_method["Both"]["client_streaming"], by_method["Both"]["server_streaming"]),
            (True, True),
        )

    def test_message_only_proto_emits_no_endpoints(self) -> None:
        # A proto without a service block declares only types; not an endpoint refusal.
        source = """syntax = "proto3";
package types;
message Money { int64 units = 1; }
enum Currency { USD = 0; EUR = 1; }
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"types.proto": source})
        self.assertEqual(_endpoints(build), [])
        self.assertEqual([f for f in build.facts if f.predicate == "EXPOSES_ENDPOINT"], [])
        self.assertEqual(build.coverage, [])

    def test_comments_and_options_do_not_break_parsing(self) -> None:
        source = """syntax = "proto3";
// leading comment with braces { } and (parens)
package svc;
/* block comment
   service NotAService { rpc Nope() } */
service Real {
  // method comment "with a quote and ; semicolon"
  rpc Do(Req) returns (Resp) {
    option (google.api.http) = { post: "/v1/do" };
  }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"svc.proto": source})
        self.assertEqual(_paths(build), {"/svc.Real/Do"})

    def test_unparsable_rpc_emits_coverage_not_a_guess(self) -> None:
        # A malformed rpc (missing returns clause) must not be guessed into an endpoint.
        source = """syntax = "proto3";
package svc;
service Broken {
  rpc Ok(Req) returns (Resp);
  rpc Bad(Req);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"svc.proto": source})
        self.assertEqual(_paths(build), {"/svc.Broken/Ok"})
        unresolved = [c for c in build.coverage if c.scope_ref.get("reason") == "unparsed_grpc_rpc"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].predicate, "EXPOSES_ENDPOINT")

    def test_adapter_emits_grpc_endpoints_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "basket.proto").write_text(_BASKET_PROTO, encoding="utf-8")
            repo = discover_repo(Path(tmp))
            result = CONFIG_GRPC_PROTO_ADAPTER.extract(repo, ExtractionContext(tenant_id="default"))
        grpc_paths = {
            e.identity["path"] for e in result.entities if e.identity.get("protocol") == "grpc"
        }
        self.assertEqual(len(grpc_paths), 3)

    def test_multiple_services_one_file(self) -> None:
        source = """syntax = "proto3";
package shop;
service Cart { rpc Add(AddReq) returns (AddResp); }
service Catalog { rpc List(ListReq) returns (ListResp); rpc Get(GetReq) returns (Item); }
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"shop.proto": source})
        self.assertEqual(
            _paths(build),
            {"/shop.Cart/Add", "/shop.Catalog/List", "/shop.Catalog/Get"},
        )

    def test_qualified_message_types_preserved(self) -> None:
        source = """syntax = "proto3";
package svc;
import "google/protobuf/empty.proto";
service S {
  rpc Ping(google.protobuf.Empty) returns (google.protobuf.Empty);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"s.proto": source})
        endpoint = _endpoints(build)[0]
        self.assertEqual(endpoint.properties["request_type"], "google.protobuf.Empty")
        self.assertEqual(endpoint.properties["response_type"], "google.protobuf.Empty")

    def test_root_qualified_leading_dot_type_names(self) -> None:
        # Leading-dot (root-qualified) type names are valid proto and must parse.
        source = """syntax = "proto3";
package svc;
service S {
  rpc Ping(.google.protobuf.Empty) returns (.svc.Pong);
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"s.proto": source})
        self.assertEqual(_paths(build), {"/svc.S/Ping"})
        endpoint = _endpoints(build)[0]
        self.assertEqual(endpoint.properties["request_type"], "google.protobuf.Empty")
        self.assertEqual(endpoint.properties["response_type"], "svc.Pong")

    def test_rpc_without_terminator_is_refused(self) -> None:
        # A proper rpc statement must end with ";" or an options block. An unterminated
        # signature is malformed and must not be surfaced as an endpoint.
        source = """syntax = "proto3";
package svc;
service S {
  rpc Bad(Req) returns (Resp)
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            build = _extract(tmp, {"s.proto": source})
        self.assertEqual(_endpoints(build), [])
        unresolved = [c for c in build.coverage if c.scope_ref.get("reason") == "unparsed_grpc_rpc"]
        self.assertEqual(len(unresolved), 1)


class ProtoParserUnitTest(unittest.TestCase):
    def test_parse_returns_no_services_for_plain_text(self) -> None:
        result = parse_proto_services("this is not a proto file at all")
        self.assertEqual(result.services, [])
        self.assertEqual(result.unparsed_rpc_lines, [])


if __name__ == "__main__":
    unittest.main()
