from __future__ import annotations

import os


DEFAULT_TENANT_ID = "default"
TENANT_ID_ENV_VAR = "SUPERCONTEXT_TENANT_ID"


def resolve_tenant_id(tenant_id: str | None = None) -> str:
    explicit = (tenant_id or "").strip()
    if explicit:
        return explicit
    env_value = os.getenv(TENANT_ID_ENV_VAR, "").strip()
    return env_value or DEFAULT_TENANT_ID
