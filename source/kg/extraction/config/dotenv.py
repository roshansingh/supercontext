import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import dotenv as _dotenv

sys.modules[__name__] = _dotenv
