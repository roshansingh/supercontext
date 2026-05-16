import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats.adapters import config_serverless_yaml as _config_serverless_yaml

sys.modules[__name__] = _config_serverless_yaml
