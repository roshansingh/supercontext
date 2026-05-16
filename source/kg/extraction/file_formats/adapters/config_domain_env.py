import sys

from source.kg.file_formats.adapters import config_domain_env as _config_domain_env

sys.modules[__name__] = _config_domain_env
