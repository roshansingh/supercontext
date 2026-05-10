from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointRoute:
    method: str
    path: str
    line: int
    source_kind: str
