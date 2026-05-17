from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from source.kg.core.models import JsonObject


MetricState = Literal["usable", "partial", "n_a"]
METRIC_STATES = frozenset({"usable", "partial", "n_a"})


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    state: MetricState
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in METRIC_STATES:
            raise ValueError(f"MetricValue.state must be one of {sorted(METRIC_STATES)}")
        if self.state == "n_a":
            if self.value is not None:
                raise ValueError("MetricValue.value must be None when state is n_a")
            if not self.reason:
                raise ValueError("MetricValue.reason is required when state is n_a")
            return
        if self.value is None:
            raise ValueError("MetricValue.value is required unless state is n_a")
        if self.state == "usable" and self.reason is not None:
            raise ValueError("MetricValue.reason must be None when state is usable")
        if self.state == "partial" and not self.reason:
            raise ValueError("MetricValue.reason is required when state is partial")

    def to_record(self) -> JsonObject:
        return {"value": self.value, "state": self.state, "reason": self.reason}


@dataclass(frozen=True)
class CellMetrics:
    repo: str
    dimension: str | None
    metric_values: dict[str, MetricValue]
    cell_score: float | None
    contract_flags: tuple[str, ...]
    commit_sha_set: tuple[str, ...]

    def to_record(self) -> JsonObject:
        return {
            "repo": self.repo,
            "dimension": self.dimension,
            "metric_values": {
                name: value.to_record()
                for name, value in sorted(self.metric_values.items())
            },
            "cell_score": self.cell_score,
            "contract_flags": list(self.contract_flags),
            "commit_sha_set": list(self.commit_sha_set),
        }
