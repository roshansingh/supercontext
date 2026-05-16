import sys

from source.kg.file_formats.adapters import config_dotenv as _config_dotenv

sys.modules[__name__] = _config_dotenv
