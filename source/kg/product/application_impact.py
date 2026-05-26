from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.call_site import call_site_from_qualifier
from source.kg.query.snapshot import KgSnapshot


RUNTIME_PREDICATES = {
    "EXPOSES_ENDPOINT",
    "DOCUMENTS_ENDPOINT",
    "REFERENCES_EVENT_CHANNEL",
    "CONSUMES_EVENT",
    "PRODUCES_EVENT",
}


@dataclass(frozen=True)
class _AppAnchor:
    root: str
    source_kind: str
    source: str


def application_impact_packet(
    kg: KgSnapshot,
    *,
    repo: str,
    changed_files: list[str],
    changed_symbols: list[JsonObject],
    limit: int,
) -> JsonObject:
    section_limit = min(limit, 20)
    anchors = _app_anchors(changed_files=changed_files, changed_symbols=changed_symbols)
    repo_key = _normalize_repo(repo)
    if not anchors or repo_key is None:
        return _empty_packet(status="missing_anchor" if repo_key else "missing_repo", limit=section_limit)

    same_repo_entities = [
        entity
        for entity in kg.entities
        if _normalize_repo(_entity_repo(entity)) == repo_key and _entity_matches_anchors(entity, anchors)
    ]
    runtime_rows = _runtime_rows(kg, repo_key=repo_key, anchors=anchors)
    worker_rows = _role_rows(same_repo_entities, role="worker")
    scheduled_rows = _role_rows(same_repo_entities, role="scheduled_job")
    api_rows = _role_rows(same_repo_entities, role="api")
    serializer_rows = _role_rows(same_repo_entities, role="serializer")
    model_rows = _role_rows(same_repo_entities, role="model")
    cross_repo_leads = _cross_repo_name_leads(kg, repo_key=repo_key, anchors=anchors, limit=section_limit)

    return {
        "status": "found" if same_repo_entities or runtime_rows or cross_repo_leads else "empty",
        "summary": {
            "app_anchor_count": len(anchors),
            "same_repo_entity_count": len(same_repo_entities),
            "api_surface_count": len(api_rows),
            "model_surface_count": len(model_rows),
            "serializer_surface_count": len(serializer_rows),
            "worker_surface_count": len(worker_rows),
            "scheduled_job_surface_count": len(scheduled_rows),
            "runtime_fact_count": len(runtime_rows),
            "cross_repo_name_lead_count": len(cross_repo_leads),
            "section_limit": section_limit,
        },
        "anchors": [_anchor_row(anchor) for anchor in anchors],
        "same_repo_surfaces": {
            "api": api_rows[:section_limit],
            "models": model_rows[:section_limit],
            "serializers": serializer_rows[:section_limit],
            "workers": worker_rows[:section_limit],
            "scheduled_jobs": scheduled_rows[:section_limit],
        },
        "runtime_facts": runtime_rows[:section_limit],
        "cross_repo_name_leads": cross_repo_leads[:section_limit],
        "assembly_contract": _ASSEMBLY_CONTRACT,
    }


def _empty_packet(*, status: str, limit: int) -> JsonObject:
    return {
        "status": status,
        "summary": {
            "app_anchor_count": 0,
            "same_repo_entity_count": 0,
            "api_surface_count": 0,
            "model_surface_count": 0,
            "serializer_surface_count": 0,
            "worker_surface_count": 0,
            "scheduled_job_surface_count": 0,
            "runtime_fact_count": 0,
            "cross_repo_name_lead_count": 0,
            "section_limit": limit,
        },
        "anchors": [],
        "same_repo_surfaces": {
            "api": [],
            "models": [],
            "serializers": [],
            "workers": [],
            "scheduled_jobs": [],
        },
        "runtime_facts": [],
        "cross_repo_name_leads": [],
        "assembly_contract": _ASSEMBLY_CONTRACT,
    }


def _app_anchors(*, changed_files: list[str], changed_symbols: list[JsonObject]) -> list[_AppAnchor]:
    anchors: dict[str, _AppAnchor] = {}
    for symbol in changed_symbols:
        module = symbol.get("module")
        if isinstance(module, str) and not _is_test_module(module):
            root = _module_root(module)
            if root is not None:
                anchors.setdefault(root, _AppAnchor(root=root, source_kind="changed_symbol_module", source=module))
    for path in changed_files:
        if _is_test_path(path):
            continue
        root = _path_root(path)
        if root is not None:
            anchors.setdefault(root, _AppAnchor(root=root, source_kind="changed_file_path", source=path))
    return sorted(anchors.values(), key=lambda anchor: anchor.root)


def _module_root(module: str) -> str | None:
    parts = [part for part in module.split(".") if part]
    return parts[0] if parts else None


def _path_root(path: str) -> str | None:
    parts = [part for part in PurePosixPath(path).parts if part and part not in {".", "/"}]
    if not parts:
        return None
    if parts[0] == "src" and len(parts) > 1:
        return parts[1]
    return parts[0]


def _anchor_row(anchor: _AppAnchor) -> JsonObject:
    return {
        "root": anchor.root,
        "source_kind": anchor.source_kind,
        "source": anchor.source,
        "lead_terms": sorted(_anchor_terms(anchor.root)),
    }


def _entity_matches_anchors(entity: JsonObject, anchors: list[_AppAnchor]) -> bool:
    module = _entity_module(entity)
    path = _entity_path(entity)
    return any(_module_or_path_has_root(module=module, path=path, root=anchor.root) for anchor in anchors)


def _module_or_path_has_root(*, module: str | None, path: str | None, root: str) -> bool:
    if module and (module == root or module.startswith(f"{root}.")):
        return True
    if path:
        normalized = path.strip("/")
        if normalized == root or normalized.startswith(f"{root}/"):
            return True
    return False


def _role_rows(entities: list[JsonObject], *, role: str) -> list[JsonObject]:
    rows = [_entity_row(entity, match_basis="same_repo_app_namespace") for entity in entities if _entity_has_role(entity, role)]
    return sorted(_dedupe_rows(rows), key=_row_sort_key)


def _entity_has_role(entity: JsonObject, role: str) -> bool:
    module_segments = _segments(_entity_module(entity), separator=".")
    path_segments = _segments(_entity_path(entity), separator="/")
    symbol_kind = _entity_symbol_kind(entity)
    if role == "scheduled_job":
        return _contains_subsequence(module_segments, ("management", "commands")) or _contains_subsequence(
            path_segments, ("management", "commands")
        )
    if role == "worker":
        terms = {"task", "tasks", "worker", "workers", "job", "jobs", "consumer", "consumers", "processor", "processors"}
        return bool(set(module_segments) & terms or set(path_segments) & terms)
    if role == "api":
        terms = {"api", "apis", "view", "views", "route", "routes", "url", "urls", "controller", "controllers"}
        return bool(set(module_segments) & terms or set(path_segments) & terms)
    if role == "serializer":
        terms = {"serializer", "serializers", "schema", "schemas"}
        return bool(set(module_segments) & terms or set(path_segments) & terms)
    if role == "model":
        if symbol_kind == "django_field":
            return False
        terms = {"model", "models", "entity", "entities"}
        return bool(set(module_segments) & terms or set(path_segments) & terms)
    raise ValueError(f"Unsupported application impact role: {role}")


def _runtime_rows(kg: KgSnapshot, *, repo_key: str, anchors: list[_AppAnchor]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") not in RUNTIME_PREDICATES:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if _normalize_repo(_entity_repo(subject)) != repo_key and _normalize_repo(_entity_repo(object_)) != repo_key:
            continue
        if not (
            _entity_matches_anchors(subject, anchors)
            or _entity_matches_anchors(object_, anchors)
            or _fact_evidence_matches_anchors(kg, fact, anchors)
        ):
            continue
        rows.append(_fact_row(kg, fact, subject, object_, match_basis="same_repo_app_evidence_or_entity"))
    return sorted(_dedupe_rows(rows), key=_row_sort_key)


def _fact_evidence_matches_anchors(kg: KgSnapshot, fact: JsonObject, anchors: list[_AppAnchor]) -> bool:
    for evidence in kg.evidence_by_target.get(fact.get("fact_id"), []):
        bytes_ref = evidence.get("bytes_ref")
        if not isinstance(bytes_ref, dict):
            continue
        path = bytes_ref.get("path")
        if not isinstance(path, str):
            continue
        if any(_module_or_path_has_root(module=None, path=path, root=anchor.root) for anchor in anchors):
            return True
    return False


def _cross_repo_name_leads(kg: KgSnapshot, *, repo_key: str, anchors: list[_AppAnchor], limit: int) -> list[JsonObject]:
    terms = set()
    for anchor in anchors:
        terms.update(_anchor_terms(anchor.root))
    if not terms:
        return []
    rows_by_repo: dict[str, list[JsonObject]] = {}
    for entity in kg.entities:
        entity_repo = _normalize_repo(_entity_repo(entity))
        if entity_repo is None or entity_repo == repo_key:
            continue
        if _is_test_entity(entity):
            continue
        if entity.get("kind") not in {"CodeModule", "CodeSymbol", "Service"}:
            continue
        direct_terms = sorted(term for term in terms if _entity_contains_term(entity, term))
        repo_terms = sorted(term for term in terms if _repo_contains_term(entity, term))
        surface_role = _surface_role(entity)
        if direct_terms:
            matched_terms = direct_terms
            match_basis = "name_derived_unlinked_lead"
        elif repo_terms and (entity.get("kind") == "Service" or surface_role is not None):
            matched_terms = repo_terms
            match_basis = "repo_name_derived_unlinked_lead"
        else:
            continue
        if not matched_terms:
            continue
        rows_by_repo.setdefault(entity_repo, []).append(
            {
                **_entity_row(entity, match_basis="name_derived_unlinked_lead"),
                "match_basis": match_basis,
                "matched_terms": matched_terms,
                "surface_role": surface_role,
                "interpretation": (
                    "Unlinked cross-repo lead derived from the changed app namespace. "
                    "Use as a source-inspection starting point only, not as impact proof."
                ),
            }
        )
    sorted_by_repo = {
        repo: sorted(_dedupe_rows(rows), key=_lead_sort_key)
        for repo, rows in rows_by_repo.items()
    }
    diversified: list[JsonObject] = []
    while len(diversified) < limit and sorted_by_repo:
        for repo in sorted(sorted_by_repo):
            rows = sorted_by_repo.get(repo, [])
            if not rows:
                sorted_by_repo.pop(repo, None)
                continue
            diversified.append(rows.pop(0))
            if len(diversified) >= limit:
                break
    return diversified


def _anchor_terms(root: str) -> set[str]:
    normalized = _normalize_token(root)
    if not normalized:
        return set()
    terms = {normalized}
    if normalized.endswith("ies") and len(normalized) > 3:
        terms.add(f"{normalized[:-3]}y")
    elif normalized.endswith("s") and len(normalized) > 3:
        terms.add(normalized[:-1])
    return terms


def _entity_contains_term(entity: JsonObject, term: str) -> bool:
    repo = _entity_repo(entity)
    values = [
        _entity_module_without_repo_prefix(_entity_module(entity), repo),
        _entity_path(entity),
        _entity_qualname(entity),
    ]
    for value in values:
        if not isinstance(value, str):
            continue
        tokens = {_normalize_token(token) for token in _split_identifier(value)}
        if term in tokens:
            return True
    return False


def _repo_contains_term(entity: JsonObject, term: str) -> bool:
    repo = _entity_repo(entity)
    if not isinstance(repo, str):
        return False
    return term in {_normalize_token(token) for token in _split_identifier(repo)}


def _surface_role(entity: JsonObject) -> str | None:
    for role in ("api", "serializer", "worker", "scheduled_job", "model"):
        if _entity_has_role(entity, role):
            return role
    return None


def _is_test_entity(entity: JsonObject) -> bool:
    path = _entity_path(entity)
    if not isinstance(path, str):
        return False
    return _is_test_path(path)


def _is_test_path(path: str) -> bool:
    segments = {_normalize_token(part) for part in path.split("/") if part}
    filename = PurePosixPath(path).name.lower()
    return (
        bool({"test", "tests", "__tests__"} & segments)
        or filename.startswith("test_")
        or "_test." in filename
        or ".test." in filename
        or ".spec." in filename
    )


def _is_test_module(module: str) -> bool:
    parts = [_normalize_token(part) for part in module.split(".") if part]
    return bool(parts) and (
        bool({"test", "tests", "__tests__"} & set(parts))
        or any(part.startswith("test_") or part.endswith("_test") for part in parts)
    )


def _entity_module_without_repo_prefix(module: str | None, repo: str | None) -> str | None:
    if not isinstance(module, str) or not isinstance(repo, str):
        return module
    repo_token = _normalize_token(repo)
    parts = module.split(".")
    if parts and _normalize_token(parts[0]) == repo_token:
        return ".".join(parts[1:])
    return module


def _split_identifier(value: str) -> list[str]:
    normalized = value.replace("/", " ").replace(".", " ").replace("-", " ").replace("_", " ")
    parts: list[str] = []
    for token in normalized.split():
        current = []
        for char in token:
            if current and char.isupper() and not current[-1].isupper():
                parts.append("".join(current))
                current = [char]
            else:
                current.append(char)
        if current:
            parts.append("".join(current))
    return parts


def _normalize_token(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _segments(value: str | None, *, separator: str) -> list[str]:
    if not value:
        return []
    return [_normalize_token(part) for part in value.split(separator) if _normalize_token(part)]


def _contains_subsequence(segments: list[str], subsequence: tuple[str, ...]) -> bool:
    if len(segments) < len(subsequence):
        return False
    for index in range(0, len(segments) - len(subsequence) + 1):
        if tuple(segments[index : index + len(subsequence)]) == subsequence:
            return True
    return False


def _entity_row(entity: JsonObject, *, match_basis: str) -> JsonObject:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return {
        "entity_id": entity.get("entity_id"),
        "kind": entity.get("kind"),
        "name": display_entity(entity),
        "repo": identity.get("repo") or properties.get("repo"),
        "module": identity.get("module"),
        "qualname": identity.get("qualname"),
        "symbol_kind": identity.get("symbol_kind"),
        "path": properties.get("path"),
        "line": properties.get("line"),
        "end_line": properties.get("end_line"),
        "match_basis": match_basis,
    }


def _fact_row(kg: KgSnapshot, fact: JsonObject, subject: JsonObject, object_: JsonObject, *, match_basis: str) -> JsonObject:
    row = {
        "fact_id": fact.get("fact_id"),
        "predicate": fact.get("predicate"),
        "subject": display_entity(subject),
        "object": display_entity(object_),
        "qualifier": fact.get("qualifier", {}),
        "evidence": kg.evidence_by_target.get(fact.get("fact_id"), []),
        "match_basis": match_basis,
    }
    call_site = call_site_from_qualifier(fact.get("qualifier", {}))
    if call_site is not None:
        row["call_site"] = call_site
    return row


def _entity_repo(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    repo = identity.get("repo") or properties.get("repo")
    return str(repo) if repo is not None else None


def _entity_module(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    if not isinstance(identity, dict):
        return None
    module = identity.get("module")
    return str(module) if module is not None else None


def _entity_symbol_kind(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    if not isinstance(identity, dict):
        return None
    symbol_kind = identity.get("symbol_kind")
    return str(symbol_kind) if symbol_kind is not None else None


def _entity_qualname(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    if not isinstance(identity, dict):
        return None
    qualname = identity.get("qualname")
    return str(qualname) if qualname is not None else None


def _entity_path(entity: JsonObject) -> str | None:
    properties = entity.get("properties")
    if not isinstance(properties, dict):
        return None
    path = properties.get("path")
    return str(path) if path is not None else None


def _normalize_repo(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or None


def _dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    deduped: list[JsonObject] = []
    seen = set()
    for row in rows:
        key = str(row.get("fact_id") or row.get("entity_id") or row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _row_sort_key(row: JsonObject) -> tuple[str, str, int, str]:
    path = row.get("path")
    if not isinstance(path, str):
        evidence = row.get("evidence")
        if isinstance(evidence, list) and evidence:
            bytes_ref = evidence[0].get("bytes_ref") if isinstance(evidence[0], dict) else None
            if isinstance(bytes_ref, dict) and isinstance(bytes_ref.get("path"), str):
                path = bytes_ref["path"]
    line = row.get("line")
    if not isinstance(line, int):
        line = 0
    return (
        str(row.get("repo") or ""),
        path or "",
        line,
        str(row.get("name") or row.get("subject") or ""),
    )


def _lead_sort_key(row: JsonObject) -> tuple[int, int, str, int, str]:
    role_priority = {
        "api": 0,
        "worker": 1,
        "scheduled_job": 2,
        "serializer": 3,
        "model": 4,
        None: 5,
    }
    basis_priority = 0 if row.get("match_basis") == "name_derived_unlinked_lead" else 1
    base = _row_sort_key(row)
    return (basis_priority, role_priority.get(row.get("surface_role"), 5), base[1], base[2], base[3])


_ASSEMBLY_CONTRACT = (
    "Application impact is a support packet assembled from changed app/package namespace, indexed entities, "
    "typed runtime facts, and attached evidence paths. same_repo_surfaces and runtime_facts are structured static context. "
    "cross_repo_name_leads are unlinked name-derived source leads only; they must not be presented as proven impact "
    "without separate endpoint, event, import, or source evidence."
)
