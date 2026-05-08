from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib import util
from pathlib import Path
import sys
import tomllib

from source.kg.repo_source import RepoSnapshot


DEPENDENCY_ALIASES = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class ImportRef:
    raw_target: str
    line: int
    import_root: str
    imported_names: tuple[str, ...]
    alias: str | None
    level: int = 0


@dataclass(frozen=True)
class NormalizedImport:
    category: str
    target_name: str
    import_root: str
    distribution_name: str | None
    module_name: str | None
    imported_names: tuple[str, ...]
    alias: str | None
    raw_import: str
    line: int


class PythonImportNormalizer:
    def __init__(self, repo: RepoSnapshot) -> None:
        self.repo = repo
        self.module_names = {self._module_name(path) for path in repo.python_files}
        self.package_roots = self._package_roots()
        self.declared_dependencies = self._declared_dependencies()
        self.stdlib_modules = set(getattr(sys, "stdlib_module_names", set()))
        self.stdlib_modules.update(sys.builtin_module_names)

    def collect(self, tree: ast.AST, current_module: str) -> list[NormalizedImport]:
        return [self.normalize(ref, current_module) for ref in self._collect_imports(tree)]

    def normalize(self, ref: ImportRef, current_module: str) -> NormalizedImport:
        raw_target = ref.raw_target
        resolved_relative = self._resolve_relative(raw_target, ref.level, current_module)
        target = resolved_relative or raw_target
        root = target.split(".", 1)[0]

        if ref.level:
            category = "relative_internal_module" if self._is_internal(target) else "unknown"
            return self._normalized(ref, category, target, root, None, target)

        if self._is_internal(target):
            return self._normalized(ref, "internal_module", target, root, None, target)

        if root in self.stdlib_modules:
            return self._normalized(ref, "stdlib", root, root, None, None)

        distribution_name = self._distribution_name(root)
        if distribution_name:
            return self._normalized(ref, "third_party", distribution_name, root, distribution_name, None)

        if util.find_spec(root) is not None:
            return self._normalized(ref, "third_party", root, root, root, None)

        return self._normalized(ref, "unknown", root, root, None, None)

    def _normalized(
        self,
        ref: ImportRef,
        category: str,
        target_name: str,
        import_root: str,
        distribution_name: str | None,
        module_name: str | None,
    ) -> NormalizedImport:
        return NormalizedImport(
            category=category,
            target_name=target_name,
            import_root=import_root,
            distribution_name=distribution_name,
            module_name=module_name,
            imported_names=ref.imported_names,
            alias=ref.alias,
            raw_import=ref.raw_target,
            line=ref.line,
        )

    def _collect_imports(self, tree: ast.AST) -> list[ImportRef]:
        refs: list[ImportRef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    refs.append(
                        ImportRef(
                            raw_target=alias.name,
                            line=node.lineno,
                            import_root=alias.name.split(".", 1)[0],
                            imported_names=(),
                            alias=alias.asname,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".", 1)[0] if module else ""
                refs.append(
                    ImportRef(
                        raw_target=module,
                        line=node.lineno,
                        import_root=root,
                        imported_names=tuple(alias.name for alias in node.names),
                        alias=None,
                        level=node.level,
                    )
                )
        return refs

    def _resolve_relative(self, target: str, level: int, current_module: str) -> str | None:
        if not level:
            return None
        parts = current_module.split(".")
        base_parts = parts[: max(0, len(parts) - level)]
        if target:
            base_parts.extend(target.split("."))
        return ".".join(part for part in base_parts if part)

    def _is_internal(self, module_name: str) -> bool:
        if not module_name:
            return False
        if any(module_name == root or module_name.startswith(f"{root}.") for root in self.package_roots):
            return True
        if module_name in self.module_names:
            return True
        return any(name.startswith(f"{module_name}.") for name in self.module_names)

    def _distribution_name(self, import_root: str) -> str | None:
        if import_root in DEPENDENCY_ALIASES:
            return DEPENDENCY_ALIASES[import_root]
        normalized_root = import_root.replace("_", "-").lower()
        if normalized_root in self.declared_dependencies:
            return self.declared_dependencies[normalized_root]
        if import_root.lower() in self.declared_dependencies:
            return self.declared_dependencies[import_root.lower()]
        return None

    def _declared_dependencies(self) -> dict[str, str]:
        pyproject = self.repo.root / "pyproject.toml"
        if not pyproject.exists():
            return {}
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return {}
        dependencies = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        names = {
            str(name)
            for name in dependencies
            if str(name).lower() != "python"
        }
        return {name.replace("_", "-").lower(): name for name in names}

    def _package_roots(self) -> set[str]:
        pyproject = self.repo.root / "pyproject.toml"
        roots = {self.repo.name}
        if not pyproject.exists():
            return roots
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return roots
        for package in data.get("tool", {}).get("poetry", {}).get("packages", []):
            include = package.get("include") if isinstance(package, dict) else None
            if include:
                roots.add(str(include).split(".", 1)[0])
        return roots

    def _module_name(self, file_path: Path) -> str:
        relative = file_path.relative_to(self.repo.root).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        return ".".join(parts) or self.repo.name
