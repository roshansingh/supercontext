from __future__ import annotations

from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.dotnet.package_resolver import iter_dotnet_package_manifest_paths
from source.kg.languages.types import ConsumerDependency, ConsumerManifestIssue, ConsumerManifestResult


class DotnetConsumerManifestExtractor:
    """Extract declared .NET dependencies from project files."""

    language = "dotnet"

    def extract(self, repo: RepoSnapshot) -> ConsumerManifestResult:
        dependencies: list[ConsumerDependency] = []
        issues: list[ConsumerManifestIssue] = []
        for manifest_path in iter_dotnet_package_manifest_paths(repo.root):
            manifest_dependencies, manifest_issues = self._extract_csproj(manifest_path)
            dependencies.extend(manifest_dependencies)
            issues.extend(manifest_issues)
        return ConsumerManifestResult(dependencies=tuple(dependencies), issues=tuple(issues))

    def _extract_csproj(
        self,
        manifest_path: Path,
    ) -> tuple[list[ConsumerDependency], list[ConsumerManifestIssue]]:
        try:
            root = ET.fromstring(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ET.ParseError) as exc:
            return [], [
                ConsumerManifestIssue(
                    reason="cross_repo_dependency_manifest_unreadable",
                    manifest_path=manifest_path,
                    message=str(exc),
                    language=self.language,
                )
            ]

        dependencies: list[ConsumerDependency] = []
        for node in root.iter():
            node_name = _local_name(node.tag)
            if node_name == "ProjectReference":
                include = _non_empty_string(node.attrib.get("Include"))
                if include is None:
                    continue
                dependencies.append(
                    ConsumerDependency(
                        declared_name=_project_reference_name(include),
                        declared_version=None,
                        dependency_kind="ProjectReference",
                        manifest_path=manifest_path,
                        line_number=None,
                        spec_form="file_path",
                        target_url=include,
                    )
                )
            elif node_name == "PackageReference":
                include = _non_empty_string(node.attrib.get("Include"))
                if include is None:
                    continue
                dependencies.append(
                    ConsumerDependency(
                        declared_name=include,
                        declared_version=_package_reference_version(node),
                        dependency_kind="PackageReference",
                        manifest_path=manifest_path,
                        line_number=None,
                        spec_form="registry",
                        target_url=None,
                    )
                )
        return dependencies, []


def _package_reference_version(node: ET.Element) -> str | None:
    version = _non_empty_string(node.attrib.get("Version"))
    if version is not None:
        return version
    for child in node:
        if _local_name(child.tag) == "Version":
            return _non_empty_string(child.text)
    return None


def _project_reference_name(include: str) -> str:
    return PurePosixPath(include.replace("\\", "/")).stem


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
