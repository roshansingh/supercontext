from __future__ import annotations

from source.kg.models import JsonObject


def display_entity(entity: JsonObject) -> str:
    identity = entity.get("identity", {})
    kind = entity.get("kind")
    if kind == "CodeSymbol":
        return f"{identity.get('module')}.{identity.get('qualname')}"
    if kind == "CodeModule":
        return str(identity.get("module"))
    if kind == "Endpoint":
        host = identity.get("host")
        prefix = f"{host} " if host else ""
        return f"{prefix}{identity.get('method')} {identity.get('path')}"
    if kind == "EventChannel":
        return f"{identity.get('broker_kind')}:{identity.get('name')}"
    if kind == "DeployTarget":
        return f"{identity.get('type')}:{identity.get('target')}"
    if kind == "EnvVar":
        return str(identity.get("name"))
    return str(identity.get("name") or identity.get("slug") or identity)
