import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats._shared import domain_literals as _domain_literals

sys.modules[__name__] = _domain_literals
