from __future__ import annotations

from source.kg.file_formats.adapters.config_terraform import CONFIG_TERRAFORM_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("terraform", (CONFIG_TERRAFORM_ADAPTER,))
