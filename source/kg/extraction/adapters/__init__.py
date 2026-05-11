from source.kg.extraction.adapters.config_deploy_events import CONFIG_DEPLOY_EVENTS_ADAPTER
from source.kg.extraction.adapters.config_dotenv import CONFIG_DOTENV_ADAPTER
from source.kg.extraction.adapters.config_domain_env import CONFIG_DOMAIN_ENV_ADAPTER
from source.kg.extraction.adapters.config_openapi import CONFIG_OPENAPI_ADAPTER
from source.kg.extraction.adapters.legacy import (
    LEGACY_PYTHON_AST_ADAPTER,
    LEGACY_STATIC_CONFIG_ADAPTER,
    LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
)
from source.kg.extraction.adapters.python_boto3_transport import PYTHON_BOTO3_TRANSPORT_ADAPTER
from source.kg.extraction.framework.registry import validate_adapters


REGISTERED_ADAPTERS = validate_adapters(
    (
        LEGACY_STATIC_CONFIG_ADAPTER,
        CONFIG_DOTENV_ADAPTER,
        CONFIG_DOMAIN_ENV_ADAPTER,
        CONFIG_OPENAPI_ADAPTER,
        CONFIG_DEPLOY_EVENTS_ADAPTER,
        LEGACY_PYTHON_AST_ADAPTER,
        PYTHON_BOTO3_TRANSPORT_ADAPTER,
        LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
    )
)

__all__ = ["REGISTERED_ADAPTERS"]
