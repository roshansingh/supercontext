from source.kg.extraction.adapters.legacy import (
    LEGACY_PYTHON_AST_ADAPTER,
    LEGACY_STATIC_CONFIG_ADAPTER,
    LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
)
from source.kg.extraction.framework.registry import validate_unique_adapter_names


REGISTERED_ADAPTERS = (
    LEGACY_STATIC_CONFIG_ADAPTER,
    LEGACY_PYTHON_AST_ADAPTER,
    LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
)
validate_unique_adapter_names(REGISTERED_ADAPTERS)

__all__ = ["REGISTERED_ADAPTERS"]
