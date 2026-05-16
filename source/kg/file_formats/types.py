from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from source.kg.extraction.framework.adapter import Adapter


class FileFormatSupport(Protocol):
    name: str

    def adapters(self) -> tuple[Adapter, ...]: ...


@dataclass(frozen=True)
class StaticFileFormatSupport:
    name: str
    adapter_group: tuple[Adapter, ...]

    def adapters(self) -> tuple[Adapter, ...]:
        return self.adapter_group
