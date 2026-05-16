import sys

from source.kg.file_formats._shared import channel_normalization as _channel_normalization

sys.modules[__name__] = _channel_normalization
