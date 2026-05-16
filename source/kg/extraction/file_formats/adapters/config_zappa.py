import sys

from source.kg.file_formats.adapters import config_zappa as _config_zappa

sys.modules[__name__] = _config_zappa
