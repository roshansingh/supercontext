from __future__ import annotations

from source.kg.file_formats.adapters.config_grpc_proto import CONFIG_GRPC_PROTO_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport(name="grpc_proto", adapter_group=(CONFIG_GRPC_PROTO_ADAPTER,))
