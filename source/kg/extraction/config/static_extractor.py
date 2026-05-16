import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats._shared import static_config as _static_extractor

sys.modules[__name__] = _static_extractor
