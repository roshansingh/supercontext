from __future__ import annotations

import configparser
from pathlib import Path
import tomllib

from packaging.requirements import InvalidRequirement, Requirement

from source.kg.core.repo_source import IGNORED_DIRS, RepoSnapshot
from source.kg.languages.types import ConsumerDependency, ConsumerManifestIssue, ConsumerManifestResult


ROOT_REQUIREMENTS_FILENAMES = (
    "requirements.txt",
    "requirements-dev.txt",
    "dev-requirements.txt",
    "test-requirements.txt",
    "requirements-test.txt",
)


class PythonConsumerManifestExtractor:
    """Extract declared Python dependencies from common Python consumer manifests."""

    language = "python"

    def extract(self, repo: RepoSnapshot) -> ConsumerManifestResult:
        dependencies: list[ConsumerDependency] = []
        issues: list[ConsumerManifestIssue] = []

        pyproject = repo.root / "pyproject.toml"
        if pyproject.exists():
            pyproject_dependencies, pyproject_issues = self._extract_pyproject(pyproject)
            dependencies.extend(pyproject_dependencies)
            issues.extend(pyproject_issues)

        setup_cfg = repo.root / "setup.cfg"
        if setup_cfg.exists():
            setup_dependencies, setup_issues = self._extract_setup_cfg(setup_cfg)
            dependencies.extend(setup_dependencies)
            issues.extend(setup_issues)

        for requirements in _iter_requirements_manifests(repo.root):
            requirements_dependencies, requirements_issues = self._extract_requirements(requirements)
            dependencies.extend(requirements_dependencies)
            issues.extend(requirements_issues)

        return ConsumerManifestResult(dependencies=tuple(dependencies), issues=tuple(issues))

    def _extract_pyproject(
        self,
        manifest_path: Path,
    ) -> tuple[list[ConsumerDependency], list[ConsumerManifestIssue]]:
        try:
            data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            return [], [
                ConsumerManifestIssue(
                    reason="cross_repo_dependency_manifest_unreadable",
                    manifest_path=manifest_path,
                    message=str(exc),
                    language=self.language,
                )
            ]
        if not isinstance(data, dict):
            return [], []

        dependencies: list[ConsumerDependency] = []
        project = data.get("project")
        project_dependencies = project.get("dependencies") if isinstance(project, dict) else None
        if isinstance(project_dependencies, list):
            for raw_dependency in project_dependencies:
                if isinstance(raw_dependency, str):
                    dependency = _dependency_from_requirement(
                        raw_dependency,
                        dependency_kind="project.dependencies",
                        manifest_path=manifest_path,
                        line_number=None,
                    )
                    if dependency is not None:
                        dependencies.append(dependency)
        project_optional_dependencies = project.get("optional-dependencies") if isinstance(project, dict) else None
        if isinstance(project_optional_dependencies, dict):
            for extra_name, raw_dependencies in sorted(project_optional_dependencies.items()):
                if not isinstance(extra_name, str) or not isinstance(raw_dependencies, list):
                    continue
                for raw_dependency in raw_dependencies:
                    if isinstance(raw_dependency, str):
                        dependency = _dependency_from_requirement(
                            raw_dependency,
                            dependency_kind=f"project.optional-dependencies.{extra_name}",
                            manifest_path=manifest_path,
                            line_number=None,
                        )
                        if dependency is not None:
                            dependencies.append(dependency)

        poetry = _poetry_table(data)
        poetry_dependencies = poetry.get("dependencies") if isinstance(poetry, dict) else None
        if isinstance(poetry_dependencies, dict):
            for declared_name, raw_spec in sorted(poetry_dependencies.items()):
                if not isinstance(declared_name, str) or declared_name == "python":
                    continue
                dependency = _dependency_from_poetry(
                    declared_name,
                    raw_spec,
                    manifest_path=manifest_path,
                    dependency_kind="tool.poetry.dependencies",
                )
                if dependency is not None:
                    dependencies.append(dependency)
        poetry_dev_dependencies = poetry.get("dev-dependencies") if isinstance(poetry, dict) else None
        if isinstance(poetry_dev_dependencies, dict):
            dependencies.extend(
                _dependencies_from_poetry_table(
                    poetry_dev_dependencies,
                    manifest_path=manifest_path,
                    dependency_kind="tool.poetry.dev-dependencies",
                )
            )
        poetry_groups = poetry.get("group") if isinstance(poetry, dict) else None
        if isinstance(poetry_groups, dict):
            for group_name, group_data in sorted(poetry_groups.items()):
                if not isinstance(group_name, str) or not isinstance(group_data, dict):
                    continue
                group_dependencies = group_data.get("dependencies")
                if not isinstance(group_dependencies, dict):
                    continue
                dependencies.extend(
                    _dependencies_from_poetry_table(
                        group_dependencies,
                        manifest_path=manifest_path,
                        dependency_kind=f"tool.poetry.group.{group_name}.dependencies",
                    )
                )
        return dependencies, []

    def _extract_setup_cfg(
        self,
        manifest_path: Path,
    ) -> tuple[list[ConsumerDependency], list[ConsumerManifestIssue]]:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                parser.read_file(handle)
        except (OSError, UnicodeDecodeError, configparser.Error) as exc:
            return [], [
                ConsumerManifestIssue(
                    reason="cross_repo_dependency_manifest_unreadable",
                    manifest_path=manifest_path,
                    message=str(exc),
                    language=self.language,
                )
            ]

        dependencies: list[ConsumerDependency] = []
        if parser.has_option("options", "install_requires"):
            dependencies.extend(
                _dependencies_from_requirement_block(
                    parser.get("options", "install_requires"),
                    dependency_kind="setup.cfg:options.install_requires",
                    manifest_path=manifest_path,
                )
            )
        if parser.has_section("options.extras_require"):
            for extra_name, raw_dependencies in sorted(parser.items("options.extras_require")):
                dependencies.extend(
                    _dependencies_from_requirement_block(
                        raw_dependencies,
                        dependency_kind=f"setup.cfg:options.extras_require.{extra_name}",
                        manifest_path=manifest_path,
                    )
                )
        return dependencies, []

    def _extract_requirements(
        self,
        manifest_path: Path,
    ) -> tuple[list[ConsumerDependency], list[ConsumerManifestIssue]]:
        try:
            lines = manifest_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            return [], [
                ConsumerManifestIssue(
                    reason="cross_repo_dependency_manifest_unreadable",
                    manifest_path=manifest_path,
                    message=str(exc),
                    language=self.language,
                )
            ]

        dependencies: list[ConsumerDependency] = []
        for index, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if line.startswith("#"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            if not line or _is_pip_directive(line):
                continue
            dependency = _dependency_from_requirement(
                line,
                dependency_kind=_requirements_dependency_kind(manifest_path),
                manifest_path=manifest_path,
                line_number=index,
            )
            if dependency is not None:
                dependencies.append(dependency)
        return dependencies, []


def _iter_requirements_manifests(root: Path) -> tuple[Path, ...]:
    paths = [root / filename for filename in ROOT_REQUIREMENTS_FILENAMES]
    requirements_dir = root / "requirements"
    if requirements_dir.is_dir():
        paths.extend(sorted(requirements_dir.glob("*.txt")))
    return tuple(
        dict.fromkeys(
            path
            for path in paths
            if path.is_file() and not any(part in IGNORED_DIRS for part in path.relative_to(root).parts)
        )
    )


def _requirements_dependency_kind(manifest_path: Path) -> str:
    parent = manifest_path.parent
    if parent.name == "requirements":
        return f"requirements/{manifest_path.name}"
    return manifest_path.name


def _poetry_table(data: dict) -> object:
    tool = data.get("tool")
    return tool.get("poetry") if isinstance(tool, dict) else None


def _dependencies_from_poetry_table(
    raw_dependencies: dict,
    *,
    manifest_path: Path,
    dependency_kind: str,
) -> list[ConsumerDependency]:
    dependencies: list[ConsumerDependency] = []
    for declared_name, raw_spec in sorted(raw_dependencies.items()):
        if not isinstance(declared_name, str) or declared_name == "python":
            continue
        dependency = _dependency_from_poetry(
            declared_name,
            raw_spec,
            manifest_path=manifest_path,
            dependency_kind=dependency_kind,
        )
        if dependency is not None:
            dependencies.append(dependency)
    return dependencies


def _dependency_from_poetry(
    declared_name: str,
    raw_spec: object,
    *,
    manifest_path: Path,
    dependency_kind: str,
) -> ConsumerDependency | None:
    declared_version: str | None = None
    spec_form = "registry"
    target_url: str | None = None
    if isinstance(raw_spec, str):
        declared_version = raw_spec
    elif isinstance(raw_spec, dict):
        version = raw_spec.get("version")
        declared_version = version if isinstance(version, str) else None
        path = raw_spec.get("path")
        git = raw_spec.get("git")
        if isinstance(path, str) and path:
            spec_form = "file_path"
            target_url = path
        elif isinstance(git, str) and git:
            spec_form = "git_url"
            target_url = git
    else:
        spec_form = "unknown"
    return ConsumerDependency(
        declared_name=declared_name,
        declared_version=declared_version,
        dependency_kind=dependency_kind,
        manifest_path=manifest_path,
        line_number=None,
        spec_form=spec_form,
        target_url=target_url,
    )


def _dependencies_from_requirement_block(
    raw_dependencies: str,
    *,
    dependency_kind: str,
    manifest_path: Path,
) -> list[ConsumerDependency]:
    dependencies: list[ConsumerDependency] = []
    for raw_line in raw_dependencies.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or _is_pip_directive(line):
            continue
        dependency = _dependency_from_requirement(
            line,
            dependency_kind=dependency_kind,
            manifest_path=manifest_path,
            line_number=None,
        )
        if dependency is not None:
            dependencies.append(dependency)
    return dependencies


def _dependency_from_requirement(
    requirement: str,
    *,
    dependency_kind: str,
    manifest_path: Path,
    line_number: int | None,
) -> ConsumerDependency | None:
    stripped = requirement.strip()
    if not stripped:
        return None
    if stripped.startswith(("-e ", "--editable ")):
        target = stripped.split(maxsplit=1)[1].strip()
        name = _egg_name(target) or Path(target).name
        return ConsumerDependency(
            name,
            None,
            dependency_kind,
            manifest_path,
            line_number,
            _target_spec_form(target),
            target,
        )
    if stripped.startswith("git+"):
        name = _egg_name(stripped)
        if name is None:
            return None
        return ConsumerDependency(name, None, dependency_kind, manifest_path, line_number, "git_url", stripped)
    try:
        parsed = Requirement(stripped)
    except InvalidRequirement:
        return None
    target_url = parsed.url
    spec_form = _target_spec_form(target_url) if target_url is not None else "registry"
    declared_version = str(parsed.specifier) or None
    return ConsumerDependency(
        parsed.name,
        declared_version,
        dependency_kind,
        manifest_path,
        line_number,
        spec_form,
        target_url,
    )


def _target_spec_form(target: str) -> str:
    if target.startswith(("git+", "git://", "ssh://", "github:")):
        return "git_url"
    if target.startswith(("file:", "../", "./", "/")):
        return "file_path"
    return "unknown"


def _is_pip_directive(line: str) -> bool:
    return line.startswith("-") and not line.startswith(("-e ", "--editable "))


def _egg_name(target: str) -> str | None:
    marker = "#egg="
    if marker not in target:
        return None
    value = target.split(marker, 1)[1].split("&", 1)[0].strip()
    return value or None
