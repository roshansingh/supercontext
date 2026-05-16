import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats.adapters import config_zappa as _config_zappa

sys.modules[__name__] = _config_zappa
