from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from source.kg.extraction.framework.known_stacks import KNOWN_STACK_CATEGORY_PREDICATE


def load_known_stacks(path: Path) -> dict[str, str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} could not be parsed as YAML: {exc}") from exc
    if data is None:
        raise ValueError(f"{path} is empty; expected a YAML object mapping category names to import-root lists")
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object mapping category names to import-root lists")

    imports_by_root: dict[str, str] = {}
    for category, import_roots in data.items():
        if not isinstance(category, str) or not category:
            raise ValueError(f"{path} category keys must be non-empty strings")
        if category not in KNOWN_STACK_CATEGORY_PREDICATE:
            raise ValueError(f"{path} category {category!r} is not supported")
        _validate_import_roots(path, category, import_roots)
        for import_root in import_roots:
            if import_root in imports_by_root:
                raise ValueError(f"{path} import root {import_root!r} appears in multiple categories")
            imports_by_root[import_root] = category
    return imports_by_root


def _validate_import_roots(path: Path, category: str, import_roots: Any) -> None:
    if not isinstance(import_roots, list):
        raise ValueError(f"{path}: {category} must be a list of import-root strings")
    seen: set[str] = set()
    for index, import_root in enumerate(import_roots):
        if not isinstance(import_root, str) or not import_root:
            raise ValueError(f"{path}: {category}[{index}] must be a non-empty string")
        if import_root in seen:
            raise ValueError(f"{path}: {category} contains duplicate import root {import_root!r}")
        seen.add(import_root)
