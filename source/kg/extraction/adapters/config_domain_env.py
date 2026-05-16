import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats.adapters import config_domain_env as _config_domain_env

sys.modules[__name__] = _config_domain_env
