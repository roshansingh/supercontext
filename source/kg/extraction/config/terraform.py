import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.extraction.file_formats import terraform as _terraform

sys.modules[__name__] = _terraform
