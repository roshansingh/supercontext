from __future__ import annotations

import json
from dataclasses import dataclass

from source.kg.extraction.config.common import ScannedFile


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


@dataclass(frozen=True)
class OpenApiEndpoint:
    method: str
    path: str
    line: int
    source_kind: str


@dataclass(frozen=True)
class OpenApiExtraction:
    endpoints: list[OpenApiEndpoint]
    coverage_reason: str | None = None


def extract_openapi_endpoints(scanned: ScannedFile) -> OpenApiExtraction:
    if not _looks_like_openapi_file(scanned):
        return OpenApiExtraction([])
    if scanned.path.suffix == ".json":
        return _extract_from_json(scanned)
    return _extract_from_yaml(scanned)


def _extract_from_json(scanned: ScannedFile) -> OpenApiExtraction:
    try:
        data = json.loads(scanned.text)
    except json.JSONDecodeError:
        return OpenApiExtraction([], coverage_reason="openapi_json_parse_error")
    return OpenApiExtraction(_endpoints_from_document(data, scanned))


def _extract_from_yaml(scanned: ScannedFile) -> OpenApiExtraction:
    try:
        import yaml
    except ImportError:
        return OpenApiExtraction([], coverage_reason="pyyaml_unavailable")
    try:
        data = yaml.safe_load(scanned.text)
    except yaml.YAMLError:
        return OpenApiExtraction([], coverage_reason="openapi_yaml_parse_error")
    return OpenApiExtraction(_endpoints_from_document(data, scanned))


def _endpoints_from_document(data: object, scanned: ScannedFile) -> list[OpenApiEndpoint]:
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        return []
    endpoints: list[OpenApiEndpoint] = []
    for path, path_item in data["paths"].items():
        if not isinstance(path, str):
            continue
        path_line = _line_for_key(scanned, path)
        endpoints.append(OpenApiEndpoint(method="ANY", path=path, line=path_line, source_kind="openapi_path"))
        if not isinstance(path_item, dict):
            continue
        for method in path_item:
            if isinstance(method, str) and method.lower() in HTTP_METHODS:
                endpoints.append(
                    OpenApiEndpoint(
                        method=method.upper(),
                        path=path,
                        line=_line_for_key(scanned, method, start_line=path_line),
                        source_kind="openapi_method",
                    )
                )
    return endpoints


def _looks_like_openapi_file(scanned: ScannedFile) -> bool:
    suffix = scanned.path.suffix
    if suffix not in {".json", ".yaml", ".yml"}:
        return False
    lower_name = scanned.path.name.lower()
    if any(token in lower_name for token in ("openapi", "swagger")):
        return True
    return '"openapi"' in scanned.text or "openapi:" in scanned.text or '"swagger"' in scanned.text or "swagger:" in scanned.text


def _line_for_key(scanned: ScannedFile, key: str, start_line: int = 1) -> int:
    needle = str(key)
    for line_number, line in enumerate(scanned.lines[start_line - 1 :], start=start_line):
        if needle in line:
            return line_number
    return start_line
