import sys

from source.kg.file_formats import serverless_yaml as _serverless_yaml

sys.modules[__name__] = _serverless_yaml
