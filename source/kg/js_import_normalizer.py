from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from source.kg.repo_source import RepoSnapshot


NODE_BUILTINS = {
    "assert",
    "buffer",
    "child_process",
    "crypto",
    "events",
    "fs",
    "http",
    "https",
    "net",
    "os",
    "path",
    "process",
    "stream",
    "timers",
    "url",
    "util",
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

        if root in NODE_BUILTINS or root.startswith("node:"):
            node_name = root.removeprefix("node:")
            return self._normalized(ref, "node_builtin", node_name, root, None, None)

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
