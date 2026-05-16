from source.kg.extraction.adapters.legacy import (
    LEGACY_PYTHON_AST_ADAPTER,
    LEGACY_STATIC_CONFIG_ADAPTER,
    LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
)
from source.kg.extraction.adapters.python_boto3_transport import PYTHON_BOTO3_TRANSPORT_ADAPTER
from source.kg.extraction.adapters.typescript_express_routes import TYPESCRIPT_EXPRESS_ROUTES_ADAPTER
from source.kg.extraction.framework.registry import validate_adapters


REGISTERED_ADAPTERS = validate_adapters(
    (
        LEGACY_STATIC_CONFIG_ADAPTER,
        LEGACY_PYTHON_AST_ADAPTER,
        PYTHON_BOTO3_TRANSPORT_ADAPTER,
        TYPESCRIPT_EXPRESS_ROUTES_ADAPTER,
        LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
    )
)

__all__ = ["REGISTERED_ADAPTERS"]
