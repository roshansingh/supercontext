from __future__ import annotations

from pathlib import Path
import json
import re
import tomllib

from source.kg.extraction.config.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    add_fact,
    bytes_ref,
    scan_config_files,
    ScannedFile,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.config.deploy_events import extract_deploy_events
from source.kg.extraction.config.domain_env import extract_domain_env
from source.kg.extraction.config.dotenv import extract_dotenv
from source.kg.extraction.config.endpoints import extract_endpoints
from source.kg.extraction.config.serverless_yaml import extract_serverless_yaml_routes
from source.kg.core.models import Coverage, Entity, Evidence
from source.kg.core.repo_source import RepoSnapshot


class StaticConfigExtractor:
    source_system = CONFIG_SOURCE_SYSTEM

    def __init__(
        self,
        *,
        include_domain_env: bool = True,
        include_openapi: bool = True,
        include_deploy_events: bool = True,
    ) -> None:
        self.include_domain_env = include_domain_env
        self.include_openapi = include_openapi
        self.include_deploy_events = include_deploy_events

    def extract(
        self,
        repo: RepoSnapshot,
        files: list[ScannedFile] | None = None,
        tenant_id: str | None = None,
    ) -> ConfigKgBuild:
        resolved_tenant_id = resolve_tenant_id(tenant_id)
        build = ConfigKgBuild()
        repo_entity = self._repo_entity(repo, resolved_tenant_id)
        service_entity = self._service_entity(repo, resolved_tenant_id)
        build.entities.extend([repo_entity, service_entity])
        build.evidence.extend([self._repo_evidence(repo, repo_entity), self._service_evidence(repo, service_entity)])
        manifest_path = self._manifest_path(repo)
        if manifest_path is not None:
            add_fact(build, "DEFINED_IN", service_entity, repo_entity, repo, manifest_path, 1)

        if files is None:
            scan_result = scan_config_files(repo, resolved_tenant_id)
            files = list(scan_result.files)
            build.coverage.extend(scan_result.coverage)
        if self.include_domain_env:
            extract_dotenv(repo, files, service_entity, build, resolved_tenant_id)
            extract_domain_env(repo, files, service_entity, build, resolved_tenant_id)
        extract_endpoints(repo, files, service_entity, build, tenant_id=resolved_tenant_id, include_openapi=self.include_openapi)
        if self.include_deploy_events:
            extract_deploy_events(
                repo,
                files,
                service_entity,
                build,
                resolved_tenant_id,
                include_event_channel_references=True,
            )
            for scanned in files:
                extract_serverless_yaml_routes(repo, scanned, service_entity, build, resolved_tenant_id)
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="CONFIG_FACTS",
                scope_ref={"repo": repo.name, "path_prefix": "."},
                state="instrumented",
                source_system=self.source_system,
            )
        )
        return build

    def _repo_entity(self, repo: RepoSnapshot, tenant_id: str) -> Entity:
        return Entity(
            kind="Repo",
            identity={"tenant_id": tenant_id, "host": "local", "owner": repo.owner, "name": repo.name},
            properties={"path": str(repo.root), "commit_sha": repo.commit_sha},
        )

    def _service_entity(self, repo: RepoSnapshot, tenant_id: str) -> Entity:
        return Entity(
            kind="Service",
            identity={
                "tenant_id": tenant_id,
                "namespace": "default",
                "repo": repo.name,
                "slug": self._service_slug(repo),
            },
            properties={"repo": repo.name},
        )

    def _repo_evidence(self, repo: RepoSnapshot, entity: Entity) -> Evidence:
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system="git",
            source_ref={"repo_path": str(repo.root), "commit_sha": repo.commit_sha},
            confidence=1.0,
        )

    def _service_evidence(self, repo: RepoSnapshot, entity: Entity) -> Evidence:
        manifest_path = self._manifest_path(repo)
        return Evidence(
            target_type="entity",
            target_id=entity.entity_id,
            derivation_class="authoritative_declared",
            source_system=self._manifest_source_system(manifest_path) if manifest_path is not None else "git",
            source_ref={"package_name": self._package_name(repo)},
            bytes_ref=bytes_ref(repo, manifest_path, 1, 1) if manifest_path is not None else None,
            confidence=1.0,
        )

    def _manifest_path(self, repo: RepoSnapshot) -> Path | None:
        for filename in ("pyproject.toml", "package.json", "serverless.yml", "zappa_settings.json"):
            path = repo.root / filename
            if path.is_file():
                return path
        return None

    def _manifest_source_system(self, path: Path) -> str:
        if path.name in {"pyproject.toml", "package.json"}:
            return path.name.replace(".", "_")
        return self.source_system

    def _service_slug(self, repo: RepoSnapshot) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self._package_name(repo).lower()).strip("-") or repo.name

    def _package_name(self, repo: RepoSnapshot) -> str:
        pyproject = repo.root / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                data = {}
            return str(data.get("tool", {}).get("poetry", {}).get("name") or data.get("project", {}).get("name") or repo.name)

        package_json = repo.root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            return str(data.get("name") or repo.name)
        return repo.name
