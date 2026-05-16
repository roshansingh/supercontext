import sys

from source.kg.file_formats.adapters import config_terraform as _config_terraform

sys.modules[__name__] = _config_terraform
