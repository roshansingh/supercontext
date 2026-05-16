from __future__ import annotations

from source.kg.file_formats.adapters.config_serverless_yaml import CONFIG_SERVERLESS_YAML_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("serverless_yaml", (CONFIG_SERVERLESS_YAML_ADAPTER,))
