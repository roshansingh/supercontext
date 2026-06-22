from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from importlib import metadata
from importlib import util
from pathlib import Path
import sys
import tomllib

from source.kg.core.repo_source import RepoSnapshot


class _DistributionResolution(Enum):
    AMBIGUOUS = "ambiguous"


KNOWN_IMPORT_ROOT_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    "attr": ("attrs",),
    "bs4": ("beautifulsoup4",),
    "cv2": ("opencv-python", "opencv-python-headless", "opencv-contrib-python"),
    "dateutil": ("python-dateutil",),
    "pil": ("Pillow",),
    "pkg_resources": ("setuptools",),
    "sklearn": ("scikit-learn",),
    "yaml": ("PyYAML",),
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
        python_files = repo.files_by_language.get("python", ())
        self.module_names = {self._module_name(path) for path in python_files}
        self.package_modules = {self._module_name(path) for path in python_files if path.name == "__init__.py"}
        self.package_root_modules = self._package_root_modules()
        self.declared_dependencies = self._declared_dependencies()
        self.distributions_by_import_root = _distributions_by_import_root()
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
            module_name = self._resolve_internal_module(target)
            category = "relative_internal_module" if module_name is not None else "unknown"
            return self._normalized(ref, category, module_name or target, root, None, module_name or target)

        module_name = self._resolve_internal_module(target)
        if module_name is not None:
            return self._normalized(ref, "internal_module", module_name, root, None, module_name)

        if root in self.stdlib_modules:
            return self._normalized(ref, "stdlib", root, root, None, None)

        distribution_name = self._distribution_name(target, root)
        if distribution_name is _DistributionResolution.AMBIGUOUS:
            return self._normalized(ref, "unknown", root, root, None, None)
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
        package_parts = parts if current_module in self.package_modules else parts[:-1]
        base_parts = package_parts[: max(0, len(package_parts) - (level - 1))]
        if target:
            base_parts.extend(target.split("."))
        return ".".join(part for part in base_parts if part)

    def _resolve_internal_module(self, module_name: str) -> str | None:
        if not module_name:
            return None
        if self._module_exists_or_prefix(module_name):
            return module_name
        for import_root, module_root in sorted(self.package_root_modules.items(), key=lambda item: len(item[0]), reverse=True):
            if module_name != import_root and not module_name.startswith(f"{import_root}."):
                continue
            candidate = f"{module_root}{module_name.removeprefix(import_root)}"
            if self._module_exists_or_prefix(candidate):
                return candidate
        return None

    def _module_exists_or_prefix(self, module_name: str) -> bool:
        return module_name in self.module_names or any(name.startswith(f"{module_name}.") for name in self.module_names)

    def _distribution_name(self, target: str, import_root: str) -> str | _DistributionResolution | None:
        normalized_root = import_root.replace("_", "-").lower()
        if normalized_root in self.declared_dependencies:
            return self.declared_dependencies[normalized_root]
        if import_root.lower() in self.declared_dependencies:
            return self.declared_dependencies[import_root.lower()]
        distributions = self.distributions_by_import_root.get(import_root.lower(), ())
        declared_matches = [
            self.declared_dependencies[distribution.replace("_", "-").lower()]
            for distribution in distributions
            if distribution.replace("_", "-").lower() in self.declared_dependencies
        ]
        if len(declared_matches) == 1:
            return declared_matches[0]
        if len(declared_matches) > 1:
            # Namespace packages such as google.* need subpath ownership checks.
            # V0 refuses ambiguous declared matches instead of guessing.
            return _DistributionResolution.AMBIGUOUS
        for distribution in distributions:
            normalized_distribution = distribution.replace("_", "-").lower()
            if normalized_distribution in self.declared_dependencies:
                return self.declared_dependencies[normalized_distribution]
        if len(distributions) == 1:
            return distributions[0]
        known_distribution = self._known_distribution_name(import_root)
        if known_distribution:
            return known_distribution
        return None

    def _known_distribution_name(self, import_root: str) -> str | _DistributionResolution | None:
        candidates = KNOWN_IMPORT_ROOT_DISTRIBUTIONS.get(import_root.lower(), ())
        if not candidates:
            return None
        declared_matches = [
            self.declared_dependencies[candidate.replace("_", "-").lower()]
            for candidate in candidates
            if candidate.replace("_", "-").lower() in self.declared_dependencies
        ]
        if len(declared_matches) == 1:
            return declared_matches[0]
        if len(declared_matches) > 1:
            return _DistributionResolution.AMBIGUOUS
        if len(candidates) == 1:
            return candidates[0]
        return _DistributionResolution.AMBIGUOUS

    def _declared_dependencies(self) -> dict[str, str]:
        pyproject = self.repo.root / "pyproject.toml"
        if not pyproject.exists():
            return {}
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return {}
        names = set()
        poetry_dependencies = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        names.update(str(name) for name in poetry_dependencies if str(name).lower() != "python")
        project_dependencies = data.get("project", {}).get("dependencies", [])
        names.update(_requirement_name(str(dependency)) for dependency in project_dependencies)
        optional_dependencies = data.get("project", {}).get("optional-dependencies", {})
        if isinstance(optional_dependencies, dict):
            for dependencies in optional_dependencies.values():
                if isinstance(dependencies, list):
                    names.update(_requirement_name(str(dependency)) for dependency in dependencies)
        names = {name for name in names if name}
        return {name.replace("_", "-").lower(): name for name in names}

    def _package_root_modules(self) -> dict[str, str]:
        pyproject = self.repo.root / "pyproject.toml"
        roots = {self.repo.name: self.repo.name}
        for path in self.repo.files_by_language.get("python", ()):
            if path.name != "__init__.py":
                continue
            relative_parts = path.relative_to(self.repo.root).parts
            module_name = self._module_name(path)
            module_parts = module_name.split(".")
            if module_parts:
                roots.setdefault(module_parts[0], module_parts[0])
            if len(relative_parts) >= 3 and relative_parts[0] == "src":
                roots.setdefault(relative_parts[1], f"src.{relative_parts[1]}")
        if not pyproject.exists():
            return roots
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return roots
        for package in data.get("tool", {}).get("poetry", {}).get("packages", []):
            if not isinstance(package, dict):
                continue
            include = package.get("include")
            if not include:
                continue
            import_root = str(include).split(".", 1)[0]
            package_from = package.get("from")
            package_from_module = _package_from_module(package_from)
            module_root = f"{package_from_module}.{import_root}" if package_from_module else import_root
            roots.setdefault(import_root, module_root)
        return roots

    def _module_name(self, file_path: Path) -> str:
        relative = file_path.relative_to(self.repo.root).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        return ".".join(parts) or self.repo.name


def _package_from_module(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [part for part in value.replace("\\", "/").split("/") if part and part != "."]
    return ".".join(parts) or None


def _requirement_name(requirement: str) -> str:
    stripped = requirement.lstrip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    chars = []
    for char in stripped:
        if char not in allowed:
            break
        chars.append(char)
    return "".join(chars)


@lru_cache(maxsize=1)
def _distributions_by_import_root() -> dict[str, tuple[str, ...]]:
    """Map import roots to distributions visible in the runner's Python env.

    This is intentionally process-cached for the current local runner.
    Hosted per-repo venv resolution is tracked in BACKLOG.md and should
    revisit this cache scope.
    """
    package_map = metadata.packages_distributions()
    return {
        import_root.lower(): tuple(sorted(distributions))
        for import_root, distributions in package_map.items()
    }
