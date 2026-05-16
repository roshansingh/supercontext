import sys

from source.kg.file_formats.adapters import config_shared as _config_shared

sys.modules[__name__] = _config_shared
