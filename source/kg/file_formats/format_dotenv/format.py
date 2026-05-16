from __future__ import annotations

from source.kg.file_formats.adapters.config_dotenv import CONFIG_DOTENV_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("dotenv", (CONFIG_DOTENV_ADAPTER,))
