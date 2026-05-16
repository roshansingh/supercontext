import sys

from source.kg.file_formats.adapters import config_apache_vhost as _config_apache_vhost

sys.modules[__name__] = _config_apache_vhost
