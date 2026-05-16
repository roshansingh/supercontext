from __future__ import annotations

from source.kg.file_formats.adapters.event_channel_normalizer import EVENT_CHANNEL_NORMALIZER_ADAPTER
from source.kg.file_formats.types import StaticFileFormatSupport


FORMAT_SUPPORT = StaticFileFormatSupport("event_channel_normalizer", (EVENT_CHANNEL_NORMALIZER_ADAPTER,))
