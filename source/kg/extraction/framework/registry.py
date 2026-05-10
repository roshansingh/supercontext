from __future__ import annotations

from collections.abc import Iterable

from source.kg.extraction.framework.adapter import Adapter


REGISTERED_ADAPTERS: tuple[Adapter, ...] = ()


def register(adapters: Iterable[Adapter]) -> tuple[Adapter, ...]:
    """Test hook to override the registered tuple. Production uses adapters/__init__.py."""
    global REGISTERED_ADAPTERS
    REGISTERED_ADAPTERS = validate_adapters(adapters)
    return REGISTERED_ADAPTERS


def validate_adapters(adapters: Iterable[Adapter]) -> tuple[Adapter, ...]:
    validated = tuple(adapters)
    seen = set()
    for adapter in validated:
        if adapter.capability.name in seen:
            raise ValueError(f"Duplicate adapter name: {adapter.capability.name}")
        if not adapter.capability.source_system:
            raise ValueError(f"Adapter {adapter.capability.name} must declare source_system")
        seen.add(adapter.capability.name)
    return validated
