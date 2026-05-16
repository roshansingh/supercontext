import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats import apache_vhost as _apache_vhost

sys.modules[__name__] = _apache_vhost
