from __future__ import annotations

import json
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.types import ConsumerDependency, ConsumerManifestIssue, ConsumerManifestResult


DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)


class TypeScriptConsumerManifestExtractor:
    """Extract declared npm dependencies from package.json."""

    language = "typescript"

    def extract(self, repo: RepoSnapshot) -> ConsumerManifestResult:
        manifest_path = repo.root / "package.json"
        if not manifest_path.exists():
            return ConsumerManifestResult()
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ConsumerManifestResult(
                issues=(
                    ConsumerManifestIssue(
                        reason="cross_repo_dependency_manifest_unreadable",
                        manifest_path=manifest_path,
                        message=str(exc),
                        language=self.language,
                    ),
                )
            )
        if not isinstance(data, dict):
            return ConsumerManifestResult()

        dependencies: list[ConsumerDependency] = []
        for section in DEPENDENCY_SECTIONS:
            raw_dependencies = data.get(section)
            if not isinstance(raw_dependencies, dict):
                continue
            for declared_name, raw_spec in sorted(raw_dependencies.items()):
                if not isinstance(declared_name, str) or not declared_name:
                    continue
                declared_version = raw_spec if isinstance(raw_spec, str) else None
                spec_form, target_url = _classify_spec(declared_version)
                dependencies.append(
                    ConsumerDependency(
                        declared_name=declared_name,
                        declared_version=declared_version,
                        dependency_kind=section,
                        manifest_path=manifest_path,
                        line_number=None,
                        spec_form=spec_form,
                        target_url=target_url,
                    )
                )
        return ConsumerManifestResult(dependencies=tuple(dependencies))


def _classify_spec(spec: str | None) -> tuple[str, str | None]:
    if not spec:
        return "unknown", None
    stripped = spec.strip()
    if not stripped:
        return "unknown", None
    if stripped.startswith("workspace:"):
        return "workspace", stripped
    if stripped.startswith(("file:", "link:", "portal:")):
        return "file_path", stripped.split(":", 1)[1]
    if stripped.startswith(("git+", "git://", "ssh://", "github:")):
        return "git_url", stripped
    return "registry", None
