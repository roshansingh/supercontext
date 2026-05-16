import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import zappa as _zappa

sys.modules[__name__] = _zappa
