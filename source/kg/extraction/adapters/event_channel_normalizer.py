import sys

# Compatibility shim: route the legacy import path to the canonical file_formats module.
from source.kg.file_formats.adapters import event_channel_normalizer as _event_channel_normalizer

sys.modules[__name__] = _event_channel_normalizer
