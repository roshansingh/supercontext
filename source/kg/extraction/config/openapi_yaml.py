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
    if scanned.path.suffix not in {".json", ".yaml", ".yml"}:
        return OpenApiExtraction([])
    if scanned.path.suffix == ".json":
        result = _extract_from_json(scanned)
    else:
        result = _extract_from_yaml(scanned)
    if result.coverage_reason and not _filename_suggests_openapi(scanned):
        return OpenApiExtraction([])
    return result


def _extract_from_json(scanned: ScannedFile) -> OpenApiExtraction:
    try:
        data = json.loads(scanned.text)
    except json.JSONDecodeError:
        return OpenApiExtraction([], coverage_reason="openapi_json_parse_error")
    if not _is_openapi_document(data):
        return OpenApiExtraction([])
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
    if not _is_openapi_document(data):
        return OpenApiExtraction([])
    return OpenApiExtraction(_endpoints_from_document(data, scanned))


def _is_openapi_document(data: object) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("paths"), dict)
        and (isinstance(data.get("openapi"), str) or isinstance(data.get("swagger"), str))
    )


def _endpoints_from_document(data: object, scanned: ScannedFile) -> list[OpenApiEndpoint]:
    if not _is_openapi_document(data):
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


def _filename_suggests_openapi(scanned: ScannedFile) -> bool:
    lower_name = scanned.path.name.lower()
    return any(token in lower_name for token in ("openapi", "swagger"))


def _line_for_key(scanned: ScannedFile, key: str, start_line: int = 1) -> int:
    needle = str(key)
    for line_number, line in enumerate(scanned.lines[start_line - 1 :], start=start_line):
        if needle in line:
            return line_number
    return start_line
