from __future__ import annotations

from source.kg.file_formats.adapters.config_cname import CONFIG_CNAME_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("cname", (CONFIG_CNAME_ADAPTER,))
