import sys

from source.kg.file_formats import zappa as _zappa

sys.modules[__name__] = _zappa
