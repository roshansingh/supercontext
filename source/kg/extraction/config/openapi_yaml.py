import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import openapi_yaml as _openapi_yaml

sys.modules[__name__] = _openapi_yaml
