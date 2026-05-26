from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    deploy_target_entity,
    domain_entity,
)
from source.kg.file_formats._shared.domain_literals import domain_from_value


WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"})
WORKLOAD_TARGET_TYPES = {
    "Deployment": "kubernetes_deployment",
    "StatefulSet": "kubernetes_stateful_set",
    "DaemonSet": "kubernetes_daemon_set",
    "ReplicaSet": "kubernetes_replica_set",
    "Job": "kubernetes_job",
    "CronJob": "kubernetes_cron_job",
}
SUPPORTED_API_VERSIONS = frozenset(
    {
        "v1",
        "apps/v1",
        "apps/v1beta1",
        "apps/v1beta2",
        "batch/v1",
        "batch/v1beta1",
        "extensions/v1beta1",
        "networking.k8s.io/v1",
        "networking.k8s.io/v1beta1",
    }
)


@dataclass(frozen=True)
class KubernetesWorkload:
    kind: str
    name: str
    namespace: str
    labels: dict[str, str]
    selector: dict[str, str]
    container_names: tuple[str, ...]
    images: tuple[str, ...]
    line: int
    target: Entity
    service_owned: bool
    ownership_basis: str | None


@dataclass(frozen=True)
class KubernetesService:
    name: str
    namespace: str
    selector: dict[str, str]
    ports: tuple[JsonObject, ...]
    line: int


@dataclass(frozen=True)
class KubernetesIngressRoute:
    host: str
    namespace: str
    service_name: str
    path: str | None
    line: int


@dataclass(frozen=True)
class KubernetesManifestExtraction:
    workloads: list[KubernetesWorkload]
    services: list[KubernetesService]
    ingress_routes: list[KubernetesIngressRoute]
    coverage_reason: str | None = None
    coverage_reasons: tuple[JsonObject, ...] = ()


def extract_kubernetes_manifests(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    if not is_likely_kubernetes_manifest(scanned):
        return
    result = kubernetes_manifests(repo, scanned, service_entity, resolved_tenant_id)
    if result.coverage_reason:
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="DEPLOYS_VIA_CONFIG",
                scope_ref={"repo": repo.name, "file_path": scanned.relative_path, "reason": result.coverage_reason},
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
        return
    for item in result.coverage_reasons:
        scope_ref = {"repo": repo.name, "file_path": scanned.relative_path, **item}
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="ROUTES_DOMAIN_TO_DEPLOY",
                scope_ref=scope_ref,
                state="partially_instrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )

    for workload in result.workloads:
        add_entity_evidence(build, repo, workload.target, scanned.path, workload.line)
        if not workload.service_owned:
            continue
        qualifier: JsonObject = _workload_qualifier(scanned, workload)
        add_fact(
            build,
            "DEPLOYS_VIA_CONFIG",
            service_entity,
            workload.target,
            repo,
            scanned.path,
            workload.line,
            qualifier=qualifier,
        )

    workloads_by_service = _workloads_by_service(result.workloads, result.services)
    services_by_key = {(service.namespace, service.name): service for service in result.services}
    for route in result.ingress_routes:
        domain = domain_from_value(route.host)
        if domain is None:
            continue
        backend_service = services_by_key.get((route.namespace, route.service_name))
        backend_service_ports = list(backend_service.ports) if backend_service is not None else []
        domain_ref = domain_entity(repo, domain, resolved_tenant_id)
        add_entity_evidence(build, repo, domain_ref, scanned.path, route.line)
        add_fact(
            build,
            "REFERENCES_DOMAIN",
            service_entity,
            domain_ref,
            repo,
            scanned.path,
            route.line,
            qualifier={
                "source_kind": "kubernetes_ingress",
                "kubernetes_kind": "Ingress",
                "namespace": route.namespace,
                "backend_service": route.service_name,
                **({"backend_service_ports": backend_service_ports} if backend_service_ports else {}),
                "path": scanned.relative_path,
                "ingress_path": route.path or "",
            },
        )
        for workload in workloads_by_service.get((route.namespace, route.service_name), ()):
            add_fact(
                build,
                "ROUTES_DOMAIN_TO_DEPLOY",
                domain_ref,
                workload.target,
                repo,
                scanned.path,
                route.line,
                max(route.line, workload.line),
                qualifier={
                    "source_kind": "kubernetes_ingress",
                    "target_type": workload.target.identity["type"],
                    "kubernetes_kind": workload.kind,
                    "namespace": workload.namespace,
                    "workload": workload.name,
                    "backend_service": route.service_name,
                    **({"backend_service_ports": backend_service_ports} if backend_service_ports else {}),
                    "ingress_path": route.path or "",
                    "path": scanned.relative_path,
                    "match_basis": "ingress_backend_service_selector_to_workload",
                },
            )


def kubernetes_manifests(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    tenant_id: str | None = None,
) -> KubernetesManifestExtraction:
    if scanned.path.suffix.lower() not in {".yaml", ".yml"}:
        return KubernetesManifestExtraction([], [], [])
    if not is_likely_kubernetes_manifest(scanned):
        return KubernetesManifestExtraction([], [], [])
    try:
        import yaml
    except ImportError:
        if _looks_like_kubernetes_path(scanned):
            return KubernetesManifestExtraction([], [], [], coverage_reason="pyyaml_unavailable")
        return KubernetesManifestExtraction([], [], [])
    try:
        docs = list(yaml.safe_load_all(scanned.text))
    except yaml.YAMLError:
        if _looks_like_kubernetes_path(scanned):
            return KubernetesManifestExtraction([], [], [], coverage_reason="kubernetes_yaml_parse_error")
        return KubernetesManifestExtraction([], [], [])

    workloads: list[KubernetesWorkload] = []
    services: list[KubernetesService] = []
    ingress_routes: list[KubernetesIngressRoute] = []
    coverage_reasons: set[tuple[str, str, str]] = set()
    for doc in docs:
        if not _is_kubernetes_doc(doc):
            continue
        kind = str(doc.get("kind"))
        metadata = _mapping(doc.get("metadata"))
        name = _string(metadata.get("name"))
        if name is None:
            continue
        namespace = _string(metadata.get("namespace")) or "default"
        line = _line_for_value(scanned, name)
        if kind in WORKLOAD_KINDS:
            target = deploy_target_entity(
                repo,
                _target_type(kind),
                f"{scanned.relative_path}#{namespace}/{kind.lower()}/{name}",
                tenant_id,
            )
            labels = _workload_labels(doc)
            selector = _workload_selector(doc)
            container_names, images = _containers_for_workload(doc)
            service_owned, ownership_basis = _service_ownership(
                repo=repo,
                service_entity=service_entity,
                images=images,
            )
            workloads.append(
                KubernetesWorkload(
                    kind=kind,
                    name=name,
                    namespace=namespace,
                    labels=labels,
                    selector=selector,
                    container_names=container_names,
                    images=images,
                    line=line,
                    target=target,
                    service_owned=service_owned,
                    ownership_basis=ownership_basis,
                )
            )
        elif kind == "Service":
            ports, port_coverage_reasons = _service_ports(doc)
            coverage_reasons.update((reason, namespace, name) for reason in port_coverage_reasons)
            services.append(
                KubernetesService(
                    name=name,
                    namespace=namespace,
                    selector=_string_mapping(_mapping(doc.get("spec")).get("selector")),
                    ports=ports,
                    line=line,
                )
            )
        elif kind == "Ingress":
            ingress_routes.extend(_ingress_routes(doc, namespace, scanned))
    return KubernetesManifestExtraction(
        workloads,
        services,
        ingress_routes,
        coverage_reasons=tuple(
            {"reason": reason, "namespace": namespace, "service_name": service_name}
            for reason, namespace, service_name in sorted(coverage_reasons)
        ),
    )


def _workloads_by_service(
    workloads: list[KubernetesWorkload],
    services: list[KubernetesService],
) -> dict[tuple[str, str], tuple[KubernetesWorkload, ...]]:
    by_service: dict[tuple[str, str], list[KubernetesWorkload]] = {}
    for service in services:
        if not service.selector:
            continue
        matches = [
            workload
            for workload in workloads
            if workload.namespace == service.namespace and _selector_matches_labels(service.selector, workload.labels)
        ]
        if matches:
            by_service[(service.namespace, service.name)] = matches
    return {key: tuple(value) for key, value in by_service.items()}


def _selector_matches_labels(selector: dict[str, str], labels: dict[str, str]) -> bool:
    return bool(selector) and all(labels.get(key) == value for key, value in selector.items())


def _workload_qualifier(scanned: ScannedFile, workload: KubernetesWorkload) -> JsonObject:
    qualifier: JsonObject = {
        "source_kind": "kubernetes_manifest",
        "target_type": workload.target.identity["type"],
        "kubernetes_kind": workload.kind,
        "namespace": workload.namespace,
        "workload": workload.name,
        "path": scanned.relative_path,
    }
    if workload.images:
        qualifier["images"] = list(workload.images)
    if workload.container_names:
        qualifier["containers"] = list(workload.container_names)
    if workload.ownership_basis:
        qualifier["ownership_basis"] = workload.ownership_basis
    return qualifier


def _is_kubernetes_doc(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    api_version = value.get("apiVersion")
    kind = value.get("kind")
    metadata = _mapping(value.get("metadata"))
    return (
        isinstance(api_version, str)
        and api_version in SUPPORTED_API_VERSIONS
        and isinstance(kind, str)
        and kind in WORKLOAD_KINDS | {"Service", "Ingress"}
        and isinstance(metadata.get("name"), str)
    )


def _target_type(kind: str) -> str:
    return WORKLOAD_TARGET_TYPES[kind]


def _workload_labels(doc: dict[object, object]) -> dict[str, str]:
    spec = _mapping(doc.get("spec"))
    labels = _string_mapping(_mapping(_mapping(_mapping(spec.get("template")).get("metadata")).get("labels")))
    metadata_labels = _string_mapping(_mapping(_mapping(doc.get("metadata")).get("labels")))
    return {**metadata_labels, **labels}


def _workload_selector(doc: dict[object, object]) -> dict[str, str]:
    spec = _mapping(doc.get("spec"))
    selector = spec.get("selector")
    if isinstance(selector, dict):
        match_labels = _string_mapping(_mapping(selector.get("matchLabels")))
        if match_labels:
            return match_labels
    return {}


def _containers_for_workload(doc: dict[object, object]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pod_spec = _pod_spec_for_workload(doc)
    containers = pod_spec.get("containers")
    if not isinstance(containers, list):
        return (), ()
    names: list[str] = []
    images: list[str] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        name = _string(container.get("name"))
        image = _string(container.get("image"))
        if name:
            names.append(name)
        if image:
            images.append(image)
    return tuple(names), tuple(images)


def _service_ports(doc: dict[object, object]) -> tuple[tuple[JsonObject, ...], tuple[str, ...]]:
    ports = _mapping(doc.get("spec")).get("ports")
    if not isinstance(ports, list):
        return (), ()
    rows: list[JsonObject] = []
    coverage_reasons: set[str] = set()
    for port in ports:
        if not isinstance(port, dict):
            continue
        if "port" not in port or port.get("port") is None:
            coverage_reasons.add("kubernetes_service_port_missing")
        if _invalid_numeric_port(port.get("port")):
            coverage_reasons.add("kubernetes_service_port_malformed")
        if _invalid_numeric_port(port.get("nodePort")):
            coverage_reasons.add("kubernetes_service_node_port_malformed")
        row = {
            key: value
            for key, value in {
                "name": _string(port.get("name")),
                "protocol": _string(port.get("protocol")),
                "port": _numeric_port_value(port.get("port")),
                "targetPort": _target_port_value(port.get("targetPort")),
                "nodePort": _numeric_port_value(port.get("nodePort")),
            }.items()
            if value is not None
        }
        if row:
            rows.append(row)
    return tuple(rows), tuple(sorted(coverage_reasons))


def _invalid_numeric_port(value: object) -> bool:
    return value is not None and (isinstance(value, bool) or not isinstance(value, int))


def _numeric_port_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _target_port_value(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return _string(value)


def _pod_spec_for_workload(doc: dict[object, object]) -> dict[object, object]:
    kind = str(doc.get("kind"))
    spec = _mapping(doc.get("spec"))
    if kind == "CronJob":
        job_spec = _mapping(_mapping(spec.get("jobTemplate")).get("spec"))
        template = _mapping(job_spec.get("template"))
        return _mapping(template.get("spec"))
    template = _mapping(spec.get("template"))
    return _mapping(template.get("spec"))


def _ingress_routes(
    doc: dict[object, object],
    namespace: str,
    scanned: ScannedFile,
) -> list[KubernetesIngressRoute]:
    spec = _mapping(doc.get("spec"))
    rules = spec.get("rules")
    if not isinstance(rules, list):
        return []
    routes: list[KubernetesIngressRoute] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        host = _string(rule.get("host"))
        if host is None:
            continue
        http = _mapping(rule.get("http"))
        paths = http.get("paths")
        if not isinstance(paths, list):
            continue
        host_line = _line_for_value(scanned, host)
        for path_config in paths:
            if not isinstance(path_config, dict):
                continue
            service_name = _backend_service_name(_mapping(path_config.get("backend")))
            if service_name is None:
                continue
            route_path = _string(path_config.get("path"))
            routes.append(
                KubernetesIngressRoute(
                    host=host,
                    namespace=namespace,
                    service_name=service_name,
                    path=route_path,
                    line=host_line,
                )
            )
    return routes


def _backend_service_name(backend: dict[object, object]) -> str | None:
    service = _mapping(backend.get("service"))
    service_name = _string(service.get("name"))
    if service_name is not None:
        return service_name
    return _string(backend.get("serviceName"))


def _service_ownership(
    *,
    repo: RepoSnapshot,
    service_entity: Entity,
    images: tuple[str, ...],
) -> tuple[bool, str | None]:
    identity = service_entity.identity
    service_candidates = {_normalized_token(repo.name)}
    for value in (identity.get("repo"), identity.get("slug")):
        if isinstance(value, str):
            service_candidates.add(_normalized_token(value))
    service_candidates = {token for token in service_candidates if len(token) >= 4}
    image_candidates = {_normalized_token(_image_repo_name(value)) for value in images}
    image_candidates = {token for token in image_candidates if len(token) >= 4}
    overlap = sorted(service_candidates & image_candidates)
    if overlap:
        return True, f"image_repo_name_matches_service_identity:{overlap[0]}"
    return False, None


def _image_repo_name(image: str) -> str:
    without_digest = image.split("@", maxsplit=1)[0]
    last_segment = without_digest.rsplit("/", maxsplit=1)[-1]
    name, _, _tag = last_segment.partition(":")
    return name


def _normalized_token(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _mapping(value: object) -> dict[object, object]:
    return value if isinstance(value, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str):
            result[key] = item
    return result


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _line_for_value(scanned: ScannedFile, value: str) -> int:
    for line_number, line in enumerate(scanned.lines, start=1):
        if value in line:
            return line_number
    return 1


def _looks_like_kubernetes_path(scanned: ScannedFile) -> bool:
    segments = {_normalized_token(part) for part in PurePosixPath(scanned.relative_path.lower()).parts}
    return bool(segments & {"kubernetes", "k8s", "manifest", "manifests"})


def is_likely_kubernetes_manifest(scanned: ScannedFile) -> bool:
    if scanned.path.suffix.lower() not in {".yaml", ".yml"}:
        return False
    seen_api_version = False
    seen_kind = False
    checked = 0
    for line in scanned.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        checked += 1
        is_top_level = line == stripped
        if is_top_level and stripped.startswith("apiVersion:"):
            seen_api_version = True
        elif is_top_level and stripped.startswith("kind:"):
            seen_kind = True
        if seen_api_version and seen_kind:
            return True
        if checked >= 20:
            return _looks_like_kubernetes_path(scanned) and (seen_api_version or seen_kind)
    return _looks_like_kubernetes_path(scanned) and (seen_api_version or seen_kind)
