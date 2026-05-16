from __future__ import annotations

"""Discovery entry points for config and IaC file-format support.

Default discovery is cached for one process. Tests that need to mutate the
on-disk package tree should call ``reset_file_format_cache_for_tests()`` before
reading ``REGISTERED_FILE_FORMATS`` or ``file_format_adapters()`` again.
"""

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.file_formats.types import FileFormatSupport

if TYPE_CHECKING:
    from source.kg.extraction.framework.adapter import Adapter

_REGISTERED_FILE_FORMATS: tuple[FileFormatSupport, ...] | None = None


def discover_file_formats(
    package_root: Path | None = None,
    package_name: str | None = None,
) -> tuple[FileFormatSupport, ...]:
    root = package_root or Path(__file__).parent
    base_package = package_name or __package__
    if base_package is None:
        raise ValueError("package_name is required when package context is unavailable")

    formats: list[FileFormatSupport] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith("_") or child.name in {"adapters", "__pycache__"}:
            continue
        format_module = child / "format.py"
        if not format_module.exists():
            continue
        module = import_module(f"{base_package}.{child.name}.format")
        file_format = getattr(module, "FORMAT_SUPPORT", None)
        if file_format is None:
            raise ValueError(f"{child.name}.format must export FORMAT_SUPPORT")
        _validate_file_format(file_format)
        formats.append(file_format)
    _validate_unique_format_names(formats)
    return tuple(formats)


def file_format_adapters(
    formats: tuple[FileFormatSupport, ...] | None = None,
) -> tuple[Adapter, ...]:
    adapters: list[Adapter] = []
    for file_format in _registered_file_formats() if formats is None else formats:
        adapters.extend(file_format.adapters())
    return tuple(adapters)


def _registered_file_formats() -> tuple[FileFormatSupport, ...]:
    global _REGISTERED_FILE_FORMATS
    if _REGISTERED_FILE_FORMATS is None:
        _REGISTERED_FILE_FORMATS = discover_file_formats(Path(__file__).parent, __package__)
    return _REGISTERED_FILE_FORMATS


def reset_file_format_cache_for_tests() -> None:
    global _REGISTERED_FILE_FORMATS
    _REGISTERED_FILE_FORMATS = None


def _validate_file_format(file_format: FileFormatSupport) -> None:
    if not file_format.name:
        raise ValueError("File format support must declare a name")
    if not callable(getattr(file_format, "adapters", None)):
        raise ValueError(f"{file_format.name} must implement adapters()")


def _validate_unique_format_names(formats: list[FileFormatSupport]) -> None:
    seen: set[str] = set()
    for file_format in formats:
        if file_format.name in seen:
            raise ValueError(f"Duplicate file format support name: {file_format.name}")
        seen.add(file_format.name)


def __getattr__(name: str):
    if name == "REGISTERED_FILE_FORMATS":
        return _registered_file_formats()
    raise AttributeError(name)


__all__ = [
    "REGISTERED_FILE_FORMATS",
    "StaticConfigExtractor",
    "discover_file_formats",
    "file_format_adapters",
    "reset_file_format_cache_for_tests",
]
