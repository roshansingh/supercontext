from __future__ import annotations

from source.kg.file_formats.adapters.config_domain_env import CONFIG_DOMAIN_ENV_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("domain_env", (CONFIG_DOMAIN_ENV_ADAPTER,))
