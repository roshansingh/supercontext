import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import static_extractor as _static_extractor

sys.modules[__name__] = _static_extractor
