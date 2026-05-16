import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats._shared import common as _common

sys.modules[__name__] = _common
