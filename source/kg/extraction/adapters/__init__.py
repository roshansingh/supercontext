from source.kg.extraction.adapters.legacy import (
    LEGACY_PYTHON_AST_ADAPTER,
    LEGACY_STATIC_CONFIG_ADAPTER,
    LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
)
from source.kg.extraction.framework.registry import validate_adapters


REGISTERED_ADAPTERS = validate_adapters(
    (
        LEGACY_STATIC_CONFIG_ADAPTER,
        LEGACY_PYTHON_AST_ADAPTER,
        LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
    )
)

__all__ = ["REGISTERED_ADAPTERS"]
