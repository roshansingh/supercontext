from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import subprocess

from source.kg.core.repo_source import RepoSnapshot


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


class JsImportNormalizer:
    def __init__(self, repo: RepoSnapshot) -> None:
        self.repo = repo
        self.module_names = {self._module_name(path) for path in repo.typescript_files}
        self.declared_dependencies = self._declared_dependencies()
        self.node_builtins = _node_builtin_modules()

    def normalize(self, ref: JsImportRef, current_module: str) -> NormalizedJsImport:
        target = ref.raw_target
        root = self._import_root(target)

        if target.startswith("."):
            module_name = self._resolve_relative(target, current_module)
            category = "relative_internal_module" if module_name in self.module_names else "unknown"
            return self._normalized(ref, category, module_name, root, None, module_name)

        if target.startswith("@/"):
            module_name = self._path_to_module(f"src/{target[2:]}")
            category = "internal_module" if module_name in self.module_names else "unknown"
            return self._normalized(ref, category, module_name, root, None, module_name)

        node_name = self._node_builtin_name(target, root)
        if node_name:
            return self._normalized(ref, "node_builtin", node_name, self._node_builtin_root(node_name), None, None)

        distribution_name = self._distribution_name(root)
        if distribution_name:
            return self._normalized(ref, "third_party", distribution_name, root, distribution_name, None)

        module_name = self._path_to_module(target)
        if module_name in self.module_names:
            return self._normalized(ref, "internal_module", module_name, root, None, module_name)

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

    def _resolve_relative(self, target: str, current_module: str) -> str:
        current_path = Path(*current_module.split("."))
        resolved = (current_path.parent / target).as_posix()
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
        for package_json in self.repo.root.glob("**/package.json"):
            if any(part in {"node_modules", ".next"} for part in package_json.relative_to(self.repo.root).parts):
                continue
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                names.update(str(name) for name in data.get(section, {}))
        return {name.lower(): name for name in names}

    def _module_name(self, file_path: Path) -> str:
        return self._path_to_module(file_path.relative_to(self.repo.root).with_suffix("").as_posix())

    def _path_to_module(self, path: str) -> str:
        for suffix in ("/index", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs", ".mts", ".cts"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
        return ".".join(part for part in path.split("/") if part)

    def _import_root(self, target: str) -> str:
        if target.startswith("@/"):
            return "@"
        if target.startswith("@"):
            parts = target.split("/")
            return "/".join(parts[:2]) if len(parts) >= 2 else target
        return target.split("/", 1)[0]


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
