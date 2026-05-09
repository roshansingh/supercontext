"""Local KG builder and query package for the first SuperContext implementation slice."""

from source.kg.build import build_kg, build_multi_kg
from source.kg.extraction.config import StaticConfigExtractor
from source.kg.query import KgSnapshot

__all__ = ["KgSnapshot", "StaticConfigExtractor", "build_kg", "build_multi_kg"]
