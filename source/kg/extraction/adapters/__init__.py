from source.kg.extraction.file_formats.adapters.config_apache_vhost import CONFIG_APACHE_VHOST_ADAPTER
from source.kg.extraction.file_formats.adapters.config_dotenv import CONFIG_DOTENV_ADAPTER
from source.kg.extraction.file_formats.adapters.config_domain_env import CONFIG_DOMAIN_ENV_ADAPTER
from source.kg.extraction.file_formats.adapters.config_openapi import CONFIG_OPENAPI_ADAPTER
from source.kg.extraction.file_formats.adapters.config_serverless_yaml import CONFIG_SERVERLESS_YAML_ADAPTER
from source.kg.extraction.file_formats.adapters.config_terraform import CONFIG_TERRAFORM_ADAPTER
from source.kg.extraction.file_formats.adapters.config_zappa import CONFIG_ZAPPA_ADAPTER
from source.kg.extraction.file_formats.adapters.event_channel_normalizer import EVENT_CHANNEL_NORMALIZER_ADAPTER
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
        CONFIG_DOTENV_ADAPTER,
        CONFIG_DOMAIN_ENV_ADAPTER,
        CONFIG_OPENAPI_ADAPTER,
        CONFIG_TERRAFORM_ADAPTER,
        EVENT_CHANNEL_NORMALIZER_ADAPTER,
        CONFIG_APACHE_VHOST_ADAPTER,
        CONFIG_ZAPPA_ADAPTER,
        CONFIG_SERVERLESS_YAML_ADAPTER,
        LEGACY_PYTHON_AST_ADAPTER,
        PYTHON_BOTO3_TRANSPORT_ADAPTER,
        TYPESCRIPT_EXPRESS_ROUTES_ADAPTER,
        LEGACY_TYPESCRIPT_COMPILER_API_ADAPTER,
    )
)

__all__ = ["REGISTERED_ADAPTERS"]
