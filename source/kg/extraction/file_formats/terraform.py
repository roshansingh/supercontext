import sys

from source.kg.file_formats import terraform as _terraform

sys.modules[__name__] = _terraform
