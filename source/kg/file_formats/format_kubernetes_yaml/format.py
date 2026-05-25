from __future__ import annotations

from source.kg.file_formats.adapters.config_kubernetes_yaml import CONFIG_KUBERNETES_YAML_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("kubernetes_yaml", (CONFIG_KUBERNETES_YAML_ADAPTER,))
