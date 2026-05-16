import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats import domain_env as _domain_env

sys.modules[__name__] = _domain_env
