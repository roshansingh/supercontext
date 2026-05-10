from __future__ import annotations

from collections.abc import Iterable

from source.kg.extraction.framework.adapter import Adapter
from source.kg.extraction.framework.allowlists import SUPPORTED_ENTITY_KINDS, SUPPORTED_FACT_PREDICATES


REGISTERED_ADAPTERS: tuple[Adapter, ...] = ()


def register_for_tests(adapters: Iterable[Adapter]) -> tuple[Adapter, ...]:
    """Test hook to override the registered tuple. Production uses adapters/__init__.py."""
    global REGISTERED_ADAPTERS
    REGISTERED_ADAPTERS = validate_adapters(adapters)
    return REGISTERED_ADAPTERS


def validate_adapters(adapters: Iterable[Adapter]) -> tuple[Adapter, ...]:
    validated = tuple(adapters)
    seen = set()
    for adapter in validated:
        capability = adapter.capability
        if capability.name in seen:
            raise ValueError(f"Duplicate adapter name: {capability.name}")
        if not capability.source_system:
            raise ValueError(f"Adapter {capability.name} must declare source_system")
        unsupported_predicates = set(capability.produces_predicates) - SUPPORTED_FACT_PREDICATES
        if unsupported_predicates:
            raise ValueError(
                f"Adapter {capability.name} declares unsupported predicates: {sorted(unsupported_predicates)}"
            )
        unsupported_kinds = set(capability.produces_entity_kinds) - SUPPORTED_ENTITY_KINDS
        if unsupported_kinds:
            raise ValueError(f"Adapter {capability.name} declares unsupported entity kinds: {sorted(unsupported_kinds)}")
        seen.add(capability.name)
    return validated
