from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SUPPORTED_DIMENSIONS = frozenset(
    {
        "backend",
        "frontend",
        "ai-ml",
        "iac",
        "data-pipeline",
        "shared-lib",
        "mobile",
        "cli-tool",
        "docs",
    }
)


def load_dimension_rules(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} could not be parsed as YAML: {exc}") from exc
    if data is None:
        raise ValueError(f"{path} is empty; expected a dimension-rules object")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a dimension-rules object")

    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise ValueError(f"{path}: version must be a positive integer")
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise ValueError(f"{path}: rules must be a list")

    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        _validate_rule(path, index, rule, seen_ids)
    return {"version": version, "rules": rules}


def _validate_rule(path: Path, index: int, rule: Any, seen_ids: set[str]) -> None:
    if not isinstance(rule, dict):
        raise ValueError(f"{path}: rules[{index}] must be an object")
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        raise ValueError(f"{path}: rules[{index}].id must be a non-empty string")
    if rule_id in seen_ids:
        raise ValueError(f"{path}: duplicate rule id {rule_id!r}")
    seen_ids.add(rule_id)

    dimension = rule.get("dimension")
    if dimension not in SUPPORTED_DIMENSIONS:
        raise ValueError(f"{path}: rules[{index}].dimension {dimension!r} is not supported")

    has_matcher = False
    for field in ("imports", "packages", "file_extensions", "manifest_files"):
        if field in rule:
            _validate_string_list(path, f"rules[{index}].{field}", rule[field])
            has_matcher = True
    if not has_matcher:
        raise ValueError(
            f"{path}: rules[{index}] must define at least one of imports, packages, "
            "file_extensions, or manifest_files"
        )


def _validate_string_list(path: Path, label: str, value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path}: {label} must be a list")
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{path}: {label}[{index}] must be a non-empty string")
        if item in seen:
            raise ValueError(f"{path}: {label} contains duplicate value {item!r}")
        seen.add(item)
