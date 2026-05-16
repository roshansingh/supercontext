import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats._shared import channel_normalization as _channel_normalization

sys.modules[__name__] = _channel_normalization
