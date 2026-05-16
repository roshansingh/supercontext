import sys

from source.kg.file_formats import apache_vhost as _apache_vhost

sys.modules[__name__] = _apache_vhost
