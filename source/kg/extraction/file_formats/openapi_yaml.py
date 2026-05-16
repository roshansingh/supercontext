import sys

from source.kg.file_formats import openapi_yaml as _openapi_yaml

sys.modules[__name__] = _openapi_yaml
