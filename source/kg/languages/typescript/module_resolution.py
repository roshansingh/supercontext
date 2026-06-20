from __future__ import annotations

from collections.abc import Container
from dataclasses import dataclass
import json
from pathlib import Path, PureWindowsPath
import posixpath


JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
TypeScriptPathAliases = tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class _ConfigSection:
    path: Path
    config: dict[str, object]


def resolve_typescript_import_path(
    importer_path: str,
    import_source: str,
    module_paths: Container[str],
    path_aliases: TypeScriptPathAliases,
) -> str | None:
    importer_path = importer_path.replace("\\", "/")
    import_source = import_source.replace("\\", "/")
    if not import_source.startswith("."):
        return resolve_typescript_path_alias_import(import_source, module_paths, path_aliases)
    importer_dir = posixpath.dirname(importer_path)
    normalized = posixpath.normpath(posixpath.join(importer_dir, import_source))
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        return None
    return resolve_typescript_module_path_candidate(normalized, module_paths)


def resolve_typescript_path_alias_import(
    import_source: str,
    module_paths: Container[str],
    path_aliases: TypeScriptPathAliases,
) -> str | None:
    resolved = resolve_typescript_path_alias_match(import_source, module_paths, path_aliases)
    return resolved[0] if resolved is not None else None


def resolve_typescript_path_alias_match(
    import_source: str,
    module_paths: Container[str],
    path_aliases: TypeScriptPathAliases,
) -> tuple[str, str] | None:
    for pattern, targets in path_aliases:
        capture = match_typescript_path_pattern(pattern, import_source)
        if capture is None:
            continue
        pattern_has_wildcard = "*" in pattern
        for target in targets:
            if pattern_has_wildcard and target.count("*") > 1:
                continue
            candidate = target.replace("*", capture) if pattern_has_wildcard and "*" in target else target
            normalized = posixpath.normpath(candidate)
            if not normalized or normalized == "." or normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
                continue
            resolved = resolve_typescript_module_path_candidate(normalized, module_paths)
            if resolved is not None:
                return resolved, pattern
    return None


def resolve_typescript_module_path_candidate(normalized: str, module_paths: Container[str]) -> str | None:
    if not normalized or normalized.startswith("/"):
        return None
    candidates = [normalized]
    if not normalized.endswith(JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES):
        candidates.extend(f"{normalized}{suffix}" for suffix in JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES)
        candidates.extend(posixpath.join(normalized, f"index{suffix}") for suffix in JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES)
    for candidate in candidates:
        if candidate in module_paths:
            return candidate
    return None


def match_typescript_path_pattern(pattern: str, import_source: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == import_source else None
    if pattern.count("*") != 1:
        return None
    prefix, suffix = pattern.split("*", 1)
    if not import_source.startswith(prefix) or not import_source.endswith(suffix):
        return None
    return import_source[len(prefix) : len(import_source) - len(suffix) if suffix else len(import_source)]


def load_typescript_config_object(path: Path) -> dict[str, object]:
    return _load_jsonc_object(path)


def load_typescript_path_aliases(repo_root: Path) -> TypeScriptPathAliases:
    aliases: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for config_path, config in _load_typescript_configs(repo_root):
        for alias in load_typescript_path_aliases_for_config(repo_root, config_path, config):
            if alias in seen:
                continue
            seen.add(alias)
            aliases.append(alias)
    return sort_typescript_path_aliases(tuple(aliases))


def load_typescript_path_aliases_for_config(
    repo_root: Path,
    config_path: Path,
    config: dict[str, object] | None = None,
) -> TypeScriptPathAliases:
    config_data = _effective_config_section(repo_root, config_path, config, "paths")
    aliases: list[tuple[str, tuple[str, ...]]] = []
    config_dir = _config_directory(repo_root, config_data.path)
    compiler_options = config_data.config.get("compilerOptions")
    if not isinstance(compiler_options, dict):
        return ()
    paths = compiler_options.get("paths")
    if not isinstance(paths, dict):
        return ()
    base_config_data = _effective_config_section(repo_root, config_path, config, "baseUrl")
    base_compiler_options = base_config_data.config.get("compilerOptions")
    base_url = base_compiler_options.get("baseUrl") if isinstance(base_compiler_options, dict) else None
    base_config_dir = _config_directory(repo_root, base_config_data.path)
    base_prefix = _normalize_repo_relative_path(posixpath.join(base_config_dir, base_url)) if isinstance(base_url, str) else config_dir
    for pattern, raw_targets in paths.items():
        if not isinstance(pattern, str) or not isinstance(raw_targets, list):
            continue
        targets = tuple(
            _normalize_repo_relative_path(posixpath.join(base_prefix, target))
            for target in raw_targets
            if isinstance(target, str)
        )
        if targets:
            aliases.append((pattern, targets))
    return sort_typescript_path_aliases(tuple(aliases))


def sort_typescript_path_aliases(path_aliases: TypeScriptPathAliases) -> TypeScriptPathAliases:
    return tuple(sorted(path_aliases, key=_typescript_path_pattern_sort_key, reverse=True))


def load_typescript_base_urls(repo_root: Path) -> tuple[str, ...]:
    base_urls: list[str] = []
    for config_path, config in _load_typescript_configs(repo_root):
        for base_url in load_typescript_base_urls_for_config(repo_root, config_path, config):
            if base_url not in base_urls:
                base_urls.append(base_url)
    return tuple(base_urls)


def load_typescript_base_urls_for_config(
    repo_root: Path,
    config_path: Path,
    config: dict[str, object] | None = None,
) -> tuple[str, ...]:
    config_data = _effective_config_section(repo_root, config_path, config, "baseUrl")
    compiler_options = config_data.config.get("compilerOptions")
    if not isinstance(compiler_options, dict):
        return ()
    base_url = compiler_options.get("baseUrl")
    if not isinstance(base_url, str):
        return ()
    return (_normalize_repo_relative_path(posixpath.join(_config_directory(repo_root, config_data.path), base_url)),)


def _load_typescript_configs(repo_root: Path) -> tuple[tuple[Path, dict[str, object]], ...]:
    configs: list[tuple[Path, dict[str, object]]] = []
    for config_path in _root_typescript_config_paths(repo_root):
        configs.append((config_path, _load_jsonc_object(config_path)))
    return tuple(configs)


def _effective_config_section(
    repo_root: Path,
    config_path: Path,
    config: dict[str, object] | None,
    compiler_option: str,
) -> _ConfigSection:
    chain = _typescript_config_chain(repo_root, config_path, config, frozenset())
    for section in reversed(chain):
        compiler_options = section.config.get("compilerOptions")
        if isinstance(compiler_options, dict) and compiler_option in compiler_options:
            return section
    current_config = config if config is not None else _load_jsonc_object(config_path)
    return _ConfigSection(config_path, current_config)


def _typescript_config_chain(
    repo_root: Path,
    config_path: Path,
    config: dict[str, object] | None,
    seen: frozenset[Path],
) -> tuple[_ConfigSection, ...]:
    resolved_path = config_path.resolve()
    if resolved_path in seen:
        return ()
    config_data = config if config is not None else _load_jsonc_object(config_path)
    chain: list[_ConfigSection] = []
    next_seen = seen | frozenset((resolved_path,))
    for extends_value in _extends_values(config_data):
        extends_path = _resolve_extends_path(repo_root, config_path, extends_value)
        if extends_path is None:
            continue
        chain.extend(_typescript_config_chain(repo_root, extends_path, None, next_seen))
    chain.append(_ConfigSection(config_path, config_data))
    return tuple(chain)


def _extends_values(config: dict[str, object]) -> tuple[str, ...]:
    raw_extends = config.get("extends")
    if isinstance(raw_extends, str):
        return (raw_extends,)
    if isinstance(raw_extends, list):
        return tuple(value for value in raw_extends if isinstance(value, str))
    return ()


def _resolve_extends_path(repo_root: Path, config_path: Path, extends_value: str) -> Path | None:
    candidate = Path(_normalize_extends_path_value(extends_value))
    if not _is_path_like_extends_value(extends_value):
        # Package-style extends require node_modules/package export resolution; leave them unresolved.
        return None
    if PureWindowsPath(extends_value).is_absolute() and not candidate.is_absolute():
        return None
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    candidates = [candidate]
    if candidate.suffix == "":
        candidates.append(candidate.with_suffix(".json"))
        candidates.append(candidate / "tsconfig.json")
    repo_root = repo_root.resolve()
    for path in candidates:
        resolved_path = path.resolve()
        if _is_relative_to(resolved_path, repo_root) and resolved_path.is_file():
            return resolved_path
    return None


def _normalize_extends_path_value(extends_value: str) -> str:
    return PureWindowsPath(extends_value).as_posix()


def _is_path_like_extends_value(extends_value: str) -> bool:
    return (
        extends_value.startswith((".", "/", "\\"))
        or Path(extends_value).is_absolute()
        or PureWindowsPath(extends_value).is_absolute()
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _root_typescript_config_paths(repo_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for config_name in ("tsconfig.json", "jsconfig.json", "tsconfig.base.json"):
        config_path = repo_root / config_name
        if config_path.exists():
            paths.append(config_path)
    return tuple(paths)


def _config_directory(repo_root: Path, config_path: Path) -> str:
    try:
        relative_dir = config_path.resolve().parent.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return ""
    return "" if relative_dir == "." else relative_dir


def _typescript_path_pattern_sort_key(alias: tuple[str, tuple[str, ...]]) -> tuple[int, int, int]:
    pattern, _targets = alias
    if "*" not in pattern:
        return (1, len(pattern), 0)
    if pattern.count("*") != 1:
        return (-1, 0, 0)
    prefix, suffix = pattern.split("*", 1)
    return (0, len(prefix), len(suffix))


def _normalize_repo_relative_path(value: str) -> str:
    normalized = posixpath.normpath(value.replace("\\", "/"))
    return "" if normalized == "." else normalized


def _load_jsonc_object(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    try:
        data = json.loads(_strip_trailing_json_commas(_strip_jsonc_comments(text)))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _strip_jsonc_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index = min(index + 2, len(text))
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _strip_trailing_json_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)
