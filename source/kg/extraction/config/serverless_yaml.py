import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats import serverless_yaml as _serverless_yaml

sys.modules[__name__] = _serverless_yaml
