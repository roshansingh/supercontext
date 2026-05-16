from __future__ import annotations

from source.kg.file_formats.adapters.config_apache_vhost import CONFIG_APACHE_VHOST_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("apache_vhost", (CONFIG_APACHE_VHOST_ADAPTER,))
