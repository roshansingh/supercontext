from __future__ import annotations

from source.kg.extraction.framework.adapter import Adapter


REGISTERED_ADAPTERS: tuple[Adapter, ...] = ()


def register(adapters: tuple[Adapter, ...]) -> None:
    """Test hook to override the registered tuple. Production uses adapters/__init__.py."""
    global REGISTERED_ADAPTERS
    validate_unique_adapter_names(adapters)
    REGISTERED_ADAPTERS = adapters


def validate_unique_adapter_names(adapters: tuple[Adapter, ...]) -> None:
    seen = set()
    for adapter in adapters:
        if adapter.capability.name in seen:
            raise ValueError(f"Duplicate adapter name: {adapter.capability.name}")
        seen.add(adapter.capability.name)
