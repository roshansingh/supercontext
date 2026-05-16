from __future__ import annotations

from source.kg.file_formats.adapters.config_zappa import CONFIG_ZAPPA_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("zappa", (CONFIG_ZAPPA_ADAPTER,))
