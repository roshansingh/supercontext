import sys

from source.kg.file_formats.adapters import config_serverless_yaml as _config_serverless_yaml

sys.modules[__name__] = _config_serverless_yaml
