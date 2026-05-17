from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from source.kg.core.models import EvidenceDerivationClass


KNOWN_METRICS = (
    "M_inventory",
    "M_dimension_classification",
    "M_freshness",
    "M_extractor_opportunity",
    "M_evidence_grounding",
    "M_meta_coverage",
    "M_silent_gap",
    "M_trust_mix",
    "M_useful_edge",
    "M_cross_repo_linkage",
    "M_identity_health",
)
SUPPORTED_TRUST_WEIGHT_KEYS = frozenset(EvidenceDerivationClass.__args__)


@dataclass(frozen=True)
class MetricsConfig:
    enabled_metrics: tuple[str, ...]
    freshness_default_days: int
    trust_weights: dict[str, float]


def load_metrics_config(path: Path | None = None) -> MetricsConfig:
    config_path = path or Path(__file__).with_name("config.yaml")
    data = _load_yaml_mapping(config_path)

    enabled_metrics = data.get("enabled_metrics")
    if not isinstance(enabled_metrics, list) or not enabled_metrics:
        raise ValueError(f"{config_path}: enabled_metrics must be a non-empty list")
    seen: set[str] = set()
    parsed_metrics: list[str] = []
    for index, metric_name in enumerate(enabled_metrics):
        if not isinstance(metric_name, str) or not metric_name:
            raise ValueError(f"{config_path}: enabled_metrics[{index}] must be a non-empty string")
        if metric_name not in KNOWN_METRICS:
            raise ValueError(f"{config_path}: unsupported metric {metric_name!r}")
        if metric_name in seen:
            raise ValueError(f"{config_path}: duplicate metric {metric_name!r}")
        seen.add(metric_name)
        parsed_metrics.append(metric_name)

    freshness = data.get("freshness", {})
    if not isinstance(freshness, dict):
        raise ValueError(f"{config_path}: freshness must be an object")
    freshness_default_days = freshness.get("default_days", 365)
    if not isinstance(freshness_default_days, int) or freshness_default_days <= 0:
        raise ValueError(f"{config_path}: freshness.default_days must be a positive integer")

    trust_weights = _float_mapping(config_path, "trust_weights", data.get("trust_weights", {}))
    return MetricsConfig(
        enabled_metrics=tuple(parsed_metrics),
        freshness_default_days=freshness_default_days,
        trust_weights=trust_weights,
    )


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} could not be parsed as YAML: {exc}") from exc
    if data is None:
        raise ValueError(f"{path} is empty; expected a YAML object")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def _float_mapping(path: Path, field: str, value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: {field} must be an object")
    result: dict[str, float] = {}
    for key, raw_weight in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{path}: {field} keys must be non-empty strings")
        if not isinstance(raw_weight, (int, float)) or isinstance(raw_weight, bool):
            raise ValueError(f"{path}: {field}.{key} must be numeric")
        if raw_weight < 0 or raw_weight > 1:
            raise ValueError(f"{path}: {field}.{key} must be between 0 and 1")
        if key not in SUPPORTED_TRUST_WEIGHT_KEYS:
            raise ValueError(f"{path}: {field}.{key} is not a supported evidence derivation class")
        result[key] = float(raw_weight)
    return result
