import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import domain_literals as _domain_literals

sys.modules[__name__] = _domain_literals
