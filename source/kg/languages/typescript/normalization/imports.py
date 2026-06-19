from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import posixpath
import subprocess

from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot
from source.kg.languages.typescript.module_resolution import (
    TypeScriptPathAliases,
    load_typescript_base_urls,
    load_typescript_base_urls_for_config,
    load_typescript_config_object,
    load_typescript_path_aliases,
    load_typescript_path_aliases_for_config,
    match_typescript_path_pattern,
    resolve_typescript_import_path,
    resolve_typescript_module_path_candidate,
    resolve_typescript_path_alias_import,
    sort_typescript_path_aliases,
)


# Regenerate with:
# node -e "console.log(require('module').builtinModules.map(m => m.startsWith('node:') ? m.slice(5) : m).sort().join('\n'))"
FALLBACK_NODE_BUILTINS = {
    "_http_agent",
    "_http_client",
    "_http_common",
    "_http_incoming",
    "_http_outgoing",
    "_http_server",
    "_stream_duplex",
    "_stream_passthrough",
    "_stream_readable",
    "_stream_transform",
    "_stream_wrap",
    "_stream_writable",
    "_tls_common",
    "_tls_wrap",
    "assert",
    "assert/strict",
    "async_hooks",
    "buffer",
    "child_process",
    "cluster",
    "console",
    "constants",
    "crypto",
    "dgram",
    "diagnostics_channel",
    "dns",
    "dns/promises",
    "domain",
    "events",
    "fs",
    "fs/promises",
    "http",
    "http2",
    "https",
    "inspector",
    "inspector/promises",
    "module",
    "net",
    "os",
    "path",
    "path/posix",
    "path/win32",
    "perf_hooks",
    "process",
    "punycode",
    "querystring",
    "readline",
    "readline/promises",
    "repl",
    "stream",
    "stream/consumers",
    "stream/promises",
    "stream/web",
    "string_decoder",
    "sys",
    "test",
    "timers",
    "timers/promises",
    "tls",
    "trace_events",
    "tty",
    "url",
    "util",
    "util/types",
    "v8",
    "vm",
    "wasi",
    "worker_threads",
    "zlib",
}


@dataclass(frozen=True)
class JsImportRef:
    raw_target: str
    line: int
    imported_names: tuple[str, ...]
    local_names: tuple[str, ...]
    is_type_only: bool = False


@dataclass(frozen=True)
class NormalizedJsImport:
    category: str
    target_name: str
    import_root: str
    distribution_name: str | None
    module_name: str | None
    imported_names: tuple[str, ...]
    local_names: tuple[str, ...]
    raw_import: str
    line: int
    is_type_only: bool = False


@dataclass(frozen=True)
class _LocalPackage:
    name: str
    root: str
    entrypoints: tuple[str, ...]


@dataclass(frozen=True)
class _TsResolutionScope:
    path_aliases: TypeScriptPathAliases
    base_urls: tuple[str, ...]


class JsImportNormalizer:
    def __init__(self, repo: RepoSnapshot) -> None:
        self.repo = repo
        self.module_paths = {
            path.relative_to(repo.root).as_posix() for path in repo.files_by_language.get("typescript", ())
        }
        self.module_names = {self._module_name(path) for path in repo.files_by_language.get("typescript", ())}
        self.path_aliases = load_typescript_path_aliases(repo.root)
        self.base_urls = load_typescript_base_urls(repo.root)
        self.resolution_scopes = self._resolution_scopes()
        self.resolution_scope_dirs = tuple(sorted(self.resolution_scopes, key=len, reverse=True))
        self.package_json_paths = self._collect_package_json_paths()
        self.local_packages = self._local_packages()
        self.declared_dependencies = self._declared_dependencies()
        self.node_builtins = _node_builtin_modules()

    def normalize(
        self,
        ref: JsImportRef,
        current_module: str,
        current_path: str | None = None,
    ) -> NormalizedJsImport:
        target = ref.raw_target
        scope = self._resolution_scope(current_path)
        default_root = self._import_root(target)
        alias_root = self._matched_path_alias_root(target, scope.path_aliases)

        if target.startswith("."):
            module_name = self._resolve_relative(target, current_module, current_path)
            category = "relative_internal_module" if module_name in self.module_names else "unknown"
            return self._normalized(ref, category, module_name, default_root, None, module_name)

        alias_path = resolve_typescript_path_alias_import(target, self.module_paths, scope.path_aliases)
        if alias_path is not None:
            module_name = self._path_to_module(alias_path)
            return self._normalized(ref, "internal_module", module_name, alias_root or default_root, None, module_name)

        if target.startswith("@/"):
            module_path = self._resolve_module_path(f"src/{target[2:]}")
            module_name = self._path_to_module(module_path or f"src/{target[2:]}")
            category = "internal_module" if module_path is not None else "unknown"
            return self._normalized(ref, category, module_name, default_root, None, module_name)

        node_name = self._node_builtin_name(target, default_root)
        if node_name:
            return self._normalized(ref, "node_builtin", node_name, self._node_builtin_root(node_name), None, None)

        local_package_path = self._resolve_local_package_import(target, default_root)
        if local_package_path is not None:
            module_name = self._path_to_module(local_package_path)
            return self._normalized(ref, "internal_module", module_name, default_root, None, module_name)

        distribution_name = self._distribution_name(default_root)
        if distribution_name:
            return self._normalized(ref, "third_party", distribution_name, default_root, distribution_name, None)

        base_url_path = self._resolve_base_url_import(target, scope.base_urls)
        if base_url_path is not None:
            module_name = self._path_to_module(base_url_path)
            return self._normalized(ref, "internal_module", module_name, default_root, None, module_name)

        module_path = self._resolve_module_path(target)
        if module_path is not None:
            module_name = self._path_to_module(module_path)
            return self._normalized(ref, "internal_module", module_name, default_root, None, module_name)

        root = alias_root or default_root
        return self._normalized(ref, "unknown", root, root, None, None)

    def _normalized(
        self,
        ref: JsImportRef,
        category: str,
        target_name: str,
        import_root: str,
        distribution_name: str | None,
        module_name: str | None,
    ) -> NormalizedJsImport:
        return NormalizedJsImport(
            category=category,
            target_name=target_name,
            import_root=import_root,
            distribution_name=distribution_name,
            module_name=module_name,
            imported_names=ref.imported_names,
            local_names=ref.local_names,
            raw_import=ref.raw_target,
            line=ref.line,
            is_type_only=ref.is_type_only,
        )

    def _resolve_relative(self, target: str, current_module: str, current_path: str | None) -> str:
        importer_path = current_path or "/".join(current_module.split("."))
        resolved_path = resolve_typescript_import_path(importer_path, target, self.module_paths, ())
        if resolved_path is not None:
            return self._path_to_module(resolved_path)
        current_module_path = Path(*current_module.split("."))
        resolved = (current_module_path.parent / target).as_posix()
        parts: list[str] = []
        for part in resolved.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return self._path_to_module("/".join(parts))

    def _resolve_base_url_import(self, target: str, base_urls: tuple[str, ...]) -> str | None:
        for base_url in base_urls:
            candidate = posixpath.join(base_url, target) if base_url else target
            resolved = self._resolve_module_path(candidate)
            if resolved is not None:
                return resolved
        return None

    def _resolve_local_package_import(self, target: str, import_root: str) -> str | None:
        package = self.local_packages.get(import_root.lower())
        if package is None:
            return None
        subpath = target.removeprefix(package.name).lstrip("/")
        for candidate in self._local_package_candidates(package, subpath):
            resolved = self._resolve_module_path(candidate)
            if resolved is not None:
                return resolved
        return None

    def _local_package_candidates(self, package: _LocalPackage, subpath: str) -> tuple[str, ...]:
        if subpath:
            return (
                self._join_repo_path(package.root, subpath),
                self._join_repo_path(package.root, "src", subpath),
            )
        candidates = [self._join_repo_path(package.root, entrypoint) for entrypoint in package.entrypoints]
        candidates.extend(
            (
                self._join_repo_path(package.root, "src", "index"),
                self._join_repo_path(package.root, "index"),
                package.root,
            )
        )
        return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))

    def _resolve_module_path(self, target: str) -> str | None:
        normalized = posixpath.normpath(target.replace("\\", "/"))
        if normalized == ".":
            return None
        return resolve_typescript_module_path_candidate(normalized, self.module_paths)

    def _distribution_name(self, import_root: str) -> str | None:
        return self.declared_dependencies.get(import_root.lower())

    def _node_builtin_name(self, target: str, root: str) -> str | None:
        candidates = []
        if target.startswith("node:"):
            candidates.append(target.removeprefix("node:"))
        candidates.extend([target, root.removeprefix("node:")])
        for candidate in candidates:
            if candidate in self.node_builtins:
                return candidate
        return None

    def _node_builtin_root(self, node_name: str) -> str:
        return node_name.split("/", 1)[0]

    def _declared_dependencies(self) -> dict[str, str]:
        names: set[str] = set()
        for package_json in self.package_json_paths:
            data = self._read_package_json(package_json)
            if not data:
                continue
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                names.update(str(name) for name in data.get(section, {}))
        return {name.lower(): name for name in names}

    def _local_packages(self) -> dict[str, _LocalPackage]:
        packages_by_name: dict[str, list[_LocalPackage]] = {}
        for package_json in self.package_json_paths:
            data = self._read_package_json(package_json)
            raw_name = data.get("name") if data else None
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            root = package_json.parent.relative_to(self.repo.root).as_posix()
            package = _LocalPackage(
                name=raw_name.strip(),
                root="" if root == "." else root,
                entrypoints=self._package_entrypoints(data),
            )
            packages_by_name.setdefault(package.name.lower(), []).append(package)
        return {
            name: packages[0]
            for name, packages in packages_by_name.items()
            if len(packages) == 1
        }

    def _package_entrypoints(self, data: dict[str, object]) -> tuple[str, ...]:
        entrypoints: list[str] = []
        for field in ("types", "typings", "module", "main"):
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                entrypoints.append(value.strip())
        entrypoints.extend(self._exports_entrypoints(data.get("exports")))
        normalized = [self._normalize_package_entrypoint(entrypoint) for entrypoint in entrypoints]
        return tuple(dict.fromkeys(entrypoint for entrypoint in normalized if entrypoint))

    def _exports_entrypoints(self, exports: object) -> tuple[str, ...]:
        if isinstance(exports, str):
            return (exports,)
        if not isinstance(exports, dict):
            return ()
        root_export = exports.get(".") if "." in exports else exports
        if isinstance(root_export, str):
            return (root_export,)
        if not isinstance(root_export, dict):
            return ()
        entrypoints: list[str] = []
        for field in ("types", "import", "module", "require", "default"):
            value = root_export.get(field)
            if isinstance(value, str) and value.strip():
                entrypoints.append(value.strip())
        return tuple(entrypoints)

    def _collect_package_json_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for package_json in self.repo.root.glob("**/package.json"):
            if self._is_ignored_path(package_json):
                continue
            paths.append(package_json)
        return tuple(sorted(paths))

    def _read_package_json(self, path: Path) -> dict[str, object]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _is_ignored_path(self, path: Path) -> bool:
        return any(part in IGNORED_DIRS for part in path.relative_to(self.repo.root).parts)

    def _join_repo_path(self, *parts: str) -> str:
        normalized = posixpath.normpath(posixpath.join(*(part for part in parts if part)))
        return "" if normalized == "." else normalized

    def _normalize_package_entrypoint(self, entrypoint: str) -> str:
        stripped = entrypoint.strip().removeprefix("./")
        return "" if stripped == "." else posixpath.normpath(stripped.replace("\\", "/"))

    def _resolution_scopes(self) -> dict[str, _TsResolutionScope]:
        scopes: dict[str, _TsResolutionScope] = {
            "": _TsResolutionScope(path_aliases=self.path_aliases, base_urls=self.base_urls)
        }
        for config_path in self._typescript_config_paths():
            config = self._read_jsonc_object(config_path)
            config_dir = config_path.parent.relative_to(self.repo.root).as_posix()
            scope_dir = "" if config_dir == "." else config_dir
            if scope_dir == "":
                continue
            path_aliases = load_typescript_path_aliases_for_config(self.repo.root, config_path, config)
            base_urls = load_typescript_base_urls_for_config(self.repo.root, config_path, config)
            if not path_aliases and not base_urls:
                continue
            scope = _TsResolutionScope(path_aliases=path_aliases, base_urls=base_urls)
            scopes[scope_dir] = self._merge_resolution_scopes(scopes[scope_dir], scope) if scope_dir in scopes else scope
        return scopes

    def _merge_resolution_scopes(self, first: _TsResolutionScope, second: _TsResolutionScope) -> _TsResolutionScope:
        return _TsResolutionScope(
            path_aliases=sort_typescript_path_aliases(tuple(dict.fromkeys(first.path_aliases + second.path_aliases))),
            base_urls=tuple(dict.fromkeys(first.base_urls + second.base_urls)),
        )

    def _resolution_scope(self, current_path: str | None) -> _TsResolutionScope:
        if not current_path:
            return self.resolution_scopes[""]
        normalized = current_path.replace("\\", "/")
        current_dir = posixpath.dirname(normalized)
        for scope_dir in self.resolution_scope_dirs:
            if not scope_dir or current_dir == scope_dir or current_dir.startswith(f"{scope_dir}/"):
                return self.resolution_scopes[scope_dir]
        return self.resolution_scopes[""]

    def _typescript_config_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        seen: set[Path] = set()
        for config_name in ("tsconfig.json", "jsconfig.json"):
            for config_path in sorted(self.repo.root.glob(f"**/{config_name}")):
                if self._is_ignored_path(config_path):
                    continue
                if config_path in seen:
                    continue
                seen.add(config_path)
                paths.append(config_path)
        return tuple(paths)

    def _read_jsonc_object(self, path: Path) -> dict[str, object]:
        return load_typescript_config_object(path)

    def _module_name(self, file_path: Path) -> str:
        return self._path_to_module(file_path.relative_to(self.repo.root).with_suffix("").as_posix())

    def _path_to_module(self, path: str) -> str:
        for suffix in (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs", ".mts", ".cts"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        if path.endswith("/index"):
            path = path[: -len("/index")]
        return ".".join(part for part in path.split("/") if part)

    def _import_root(self, target: str) -> str:
        if target.startswith("@/"):
            return "@"
        if target.startswith("@"):
            parts = target.split("/")
            return "/".join(parts[:2]) if len(parts) >= 2 else target
        return target.split("/", 1)[0]

    def _matched_path_alias_root(self, target: str, path_aliases: TypeScriptPathAliases) -> str | None:
        pattern = self._matched_path_alias_pattern(target, path_aliases)
        if pattern is None:
            return None
        if "*" not in pattern:
            return self._import_root(pattern)
        prefix, _suffix = pattern.split("*", 1)
        return prefix.rstrip("/") or self._import_root(target)

    def _matched_path_alias_pattern(self, target: str, path_aliases: TypeScriptPathAliases) -> str | None:
        for pattern, _targets in path_aliases:
            if match_typescript_path_pattern(pattern, target) is not None:
                return pattern
        return None


@lru_cache(maxsize=1)
def _node_builtin_modules() -> set[str]:
    """Return Node builtins visible to the runner, widened by a static fallback.

    The runtime probe follows the Node executable on PATH. This keeps local OSS
    builds dependency-light; target-repo Node version resolution is backlog work.
    """
    try:
        result = subprocess.run(
            ["node", "-e", "process.stdout.write(JSON.stringify(require('module').builtinModules))"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        modules = json.loads(result.stdout or "[]")
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError):
        return set(FALLBACK_NODE_BUILTINS)
    return {str(module).removeprefix("node:") for module in modules} | set(FALLBACK_NODE_BUILTINS)
