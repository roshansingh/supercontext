import sys

from source.kg.file_formats._shared import static_config as _static_extractor

sys.modules[__name__] = _static_extractor
