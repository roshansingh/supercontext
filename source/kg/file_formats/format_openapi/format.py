from __future__ import annotations

from source.kg.file_formats.adapters.config_openapi import CONFIG_OPENAPI_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("openapi", (CONFIG_OPENAPI_ADAPTER,))
