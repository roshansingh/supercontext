from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePosixPath
import tomllib
from fnmatch import fnmatchcase

import yaml

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


OWNERSHIP_CONTEXT_CONTRACT = (
    "Only explicit ownership sources such as CODEOWNERS or service-catalog owner fields prove service ownership. "
    "Package authors and package maintainers are maintainer candidates only and must not be promoted to service owner."
)


def ownership_context_packet(
    kg: KgSnapshot,
    *,
    repo: str | None,
    services: list[JsonObject],
    limit: int,
) -> JsonObject:
    resolved_repo = _resolve_repo(repo, services)
    packet: JsonObject = {
        "scope": {"kind": "repo", "repo": resolved_repo} if resolved_repo else {"kind": "unresolved"},
        "evidence_contract": OWNERSHIP_CONTEXT_CONTRACT,
        "answer_packet": {
            "can_answer_owner": False,
            "service_identity": None,
            "proven_owner": None,
            "owner_candidates": [],
            "final_answer_guidance": "Report service owner as unknown unless an explicit ownership source is present.",
            "unsupported_promotions": [
                {
                    "candidate_kinds": ["package_author", "package_maintainer"],
                    "reason": "Packaging metadata identifies authors or maintainers of the package, not the operational service owner.",
                }
            ],
        },
        "proven_owners": [],
        "candidate_maintainers": [],
        "checked_sources": [],
        "missing_fact_families": ["service_ownership"],
        "recommended_source_checks": [
            "Check CODEOWNERS, service catalog files such as catalog-info.yaml, and explicit owner metadata before naming an owner."
        ],
    }
    if not resolved_repo:
        packet["status"] = "not_answerable"
        packet["recommended_source_checks"] = ["Retry with a repo or service anchor before answering ownership."]
        return packet
    service_identity = _service_identity(kg, resolved_repo, services)
    packet["service_identity"] = service_identity
    packet["answer_packet"]["service_identity"] = service_identity

    repo_root = _repo_root(kg, resolved_repo)
    if repo_root is None:
        packet["status"] = "partial"
        packet["checked_sources"].append({"source_kind": "snapshot_manifest", "status": "missing_repo_path"})
        packet["recommended_source_checks"] = [
            "Snapshot manifest does not expose a local repo path for source ownership checks."
        ]
        return packet

    service_paths = _service_source_paths(services)
    proven = _explicit_owners(repo_root, service_paths=service_paths, limit=limit)
    candidates = _package_maintainer_candidates(repo_root, limit=limit)
    packet["checked_sources"] = _checked_sources(repo_root)
    packet["proven_owners"] = proven
    packet["candidate_maintainers"] = candidates
    packet["answer_packet"]["owner_candidates"] = candidates
    if proven:
        packet["status"] = "answerable"
        packet["missing_fact_families"] = []
        packet["answer_packet"]["can_answer_owner"] = True
        packet["answer_packet"]["proven_owner"] = proven[0]
        packet["answer_packet"]["final_answer_guidance"] = "Answer with proven_owner and cite its source."
    else:
        packet["status"] = "partial"
    return packet


def _resolve_repo(repo: str | None, services: list[JsonObject]) -> str | None:
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    repos = {
        str(service.get("repo")).strip()
        for service in services
        if isinstance(service.get("repo"), str) and str(service.get("repo")).strip()
    }
    if len(repos) == 1:
        return next(iter(repos))
    return None


def _repo_root(kg: KgSnapshot, repo: str) -> Path | None:
    manifest = kg.manifest if isinstance(kg.manifest, dict) else {}
    repos = manifest.get("repos")
    if isinstance(repos, list):
        for row in repos:
            if not isinstance(row, dict):
                continue
            if row.get("repo_name") == repo or row.get("name") == repo:
                path = row.get("repo_path")
                if isinstance(path, str) and path:
                    root = _manifest_repo_path(kg, path)
                    return root if root.is_dir() else None
    path = manifest.get("repo_path")
    repo_name = manifest.get("repo_name") or manifest.get("name")
    if repo_name == repo and isinstance(path, str) and path:
        root = _manifest_repo_path(kg, path)
        return root if root.is_dir() else None
    return None


def _manifest_repo_path(kg: KgSnapshot, path: str) -> Path:
    root = Path(path).expanduser()
    if root.is_absolute():
        return root
    return kg.root / root


def _service_identity(kg: KgSnapshot, repo: str, services: list[JsonObject]) -> JsonObject | None:
    for service in services:
        if service.get("repo") == repo:
            row = {
                "service_id": service.get("service_id"),
                "name": service.get("name"),
                "repo": service.get("repo"),
                "namespace": service.get("namespace"),
                "slug": service.get("slug"),
            }
            if row["slug"] is not None and row["namespace"] is not None:
                return row
    for entity in kg.entities:
        if entity.get("kind") != "Service":
            continue
        identity = entity.get("identity")
        properties = entity.get("properties")
        if not isinstance(identity, dict):
            identity = {}
        if not isinstance(properties, dict):
            properties = {}
        entity_repo = identity.get("repo") or properties.get("repo")
        if entity_repo != repo:
            continue
        return {
            "service_id": entity.get("entity_id"),
            "name": display_entity(entity),
            "repo": entity_repo,
            "namespace": identity.get("namespace"),
            "slug": identity.get("slug"),
        }
    return None


def _explicit_owners(repo_root: Path, *, service_paths: list[str], limit: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    rows.extend(_codeowners_rows(repo_root, service_paths=service_paths, limit=limit))
    if len(rows) < limit:
        rows.extend(_catalog_owner_rows(repo_root, limit=limit - len(rows)))
    return rows[:limit]


def _codeowners_rows(repo_root: Path, *, service_paths: list[str], limit: int) -> list[JsonObject]:
    if limit <= 0:
        return []
    rows: list[JsonObject] = []
    for relative in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        path = repo_root / relative
        if not path.is_file():
            continue
        parsed_any = False
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            owners = _valid_codeowners_tokens(parts[1:])
            if not owners:
                continue
            parsed_any = True
            scope = _codeowners_owner_scope(parts[0], service_paths)
            if scope is None:
                continue
            rows.append(
                {
                    "owners": owners,
                    "owner_kind": "code_owner",
                    **scope,
                    "source_kind": "codeowners",
                    "scope_pattern": parts[0],
                    "source": _source_ref(relative, line_number),
                }
            )
            if len(rows) >= limit:
                return rows
        if rows or parsed_any:
            break
    return rows


def _service_source_paths(services: list[JsonObject]) -> list[str]:
    paths: list[str] = []
    for service in services:
        for key in ("path",):
            value = service.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
        for evidence in service.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            bytes_ref = evidence.get("bytes_ref")
            if not isinstance(bytes_ref, dict):
                continue
            path = bytes_ref.get("path")
            if isinstance(path, str) and path.strip():
                paths.append(path.strip())
    return _dedupe_strings(paths)


def _codeowners_owner_scope(pattern: str, service_paths: list[str]) -> JsonObject | None:
    if _codeowners_pattern_is_repo_wide(pattern):
        return {"owner_scope": "repo_wide"}
    matched_paths = [
        path
        for path in service_paths
        if _codeowners_pattern_matches_path(pattern, path)
    ]
    if matched_paths:
        return {"owner_scope": "service_path_match", "matched_service_paths": matched_paths[:3]}
    return None


def _codeowners_pattern_is_repo_wide(pattern: str) -> bool:
    normalized = pattern.strip()
    return normalized in {"*", "**", "/", "/*", "/**"}


def _codeowners_pattern_matches_path(pattern: str, path: str) -> bool:
    normalized_pattern = pattern.strip().lstrip("/")
    normalized_path = path.strip().lstrip("/")
    if not normalized_pattern or not normalized_path:
        return False
    if normalized_pattern.endswith("/"):
        prefix = normalized_pattern.rstrip("/") + "/"
        return normalized_path.startswith(prefix)
    if fnmatchcase(normalized_path, normalized_pattern):
        return True
    if "/" not in normalized_pattern and fnmatchcase(PurePosixPath(normalized_path).name, normalized_pattern):
        return True
    if normalized_pattern.endswith("/*"):
        prefix = normalized_pattern[:-2].rstrip("/") + "/"
        return normalized_path.startswith(prefix)
    literal_prefix = normalized_pattern.rstrip("/") + "/"
    return normalized_path == normalized_pattern or normalized_path.startswith(literal_prefix)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _catalog_owner_rows(repo_root: Path, *, limit: int) -> list[JsonObject]:
    if limit <= 0:
        return []
    rows: list[JsonObject] = []
    for relative in ("catalog-info.yaml", "catalog-info.yml", "service.yaml", "service.yml"):
        path = repo_root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        owner = _catalog_owner_value(data, relative=relative)
        if owner is None:
            continue
        rows.append(
            {
                "owners": [owner],
                "owner_kind": "service_catalog_owner",
                "source_kind": "service_catalog",
                "source": _source_ref(relative, _line_containing_key(text.splitlines(), "owner")),
            }
        )
        if len(rows) >= limit:
            return rows
        break
    return rows


def _catalog_owner_value(data: object, *, relative: str) -> str | None:
    if not isinstance(data, dict):
        return None
    is_catalog_file = relative.startswith("catalog-info.")
    spec = data.get("spec")
    if isinstance(spec, dict) and isinstance(spec.get("owner"), str) and spec["owner"].strip():
        if is_catalog_file or _looks_like_service_catalog(data):
            return spec["owner"].strip()
    owner = data.get("owner")
    if is_catalog_file and isinstance(owner, str) and owner.strip():
        return owner.strip()
    return None


def _looks_like_service_catalog(data: dict[object, object]) -> bool:
    api_version = data.get("apiVersion")
    kind = data.get("kind")
    return (isinstance(api_version, str) and api_version.startswith("backstage.io/")) or kind == "Component"


def _valid_codeowners_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if _is_valid_codeowners_owner(token)]


def _is_valid_codeowners_owner(token: str) -> bool:
    if token.startswith("@"):
        return len(token) > 1
    if token.count("@") != 1:
        return False
    local, domain = token.split("@", 1)
    return bool(local and domain)


def _package_maintainer_candidates(repo_root: Path, *, limit: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        rows.extend(_pyproject_candidates(pyproject, limit=limit))
    if len(rows) < limit:
        package_json = repo_root / "package.json"
        if package_json.is_file():
            rows.extend(_package_json_candidates(package_json, limit=limit - len(rows)))
    return rows[:limit]


def _pyproject_candidates(path: Path, *, limit: int) -> list[JsonObject]:
    if limit <= 0:
        return []
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    rows: list[JsonObject] = []
    lines = text.splitlines()
    authors_line = _line_containing_key(lines, "authors")
    maintainers_line = _line_containing_key(lines, "maintainers")
    project = data.get("project")
    if isinstance(project, dict):
        rows.extend(_pep621_people(project.get("authors"), "package_author", "pyproject_project_authors", path, authors_line))
        if len(rows) >= limit:
            return rows[:limit]
        rows.extend(
            _pep621_people(
                project.get("maintainers"),
                "package_maintainer",
                "pyproject_project_maintainers",
                path,
                maintainers_line,
            )
        )
        if len(rows) >= limit:
            return rows[:limit]
    poetry = data.get("tool", {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    if isinstance(poetry, dict):
        rows.extend(_string_people(poetry.get("authors"), "package_author", "pyproject_poetry_authors", path, authors_line))
        if len(rows) >= limit:
            return rows[:limit]
        rows.extend(
            _string_people(poetry.get("maintainers"), "package_maintainer", "pyproject_poetry_maintainers", path, maintainers_line)
        )
    return rows[:limit]


def _pep621_people(
    value: object, candidate_kind: str, source_kind: str, path: Path, source_line: int | None
) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        email = item.get("email")
        if not isinstance(name, str) and not isinstance(email, str):
            continue
        label = _person_label(name, email)
        if not label:
            continue
        rows.append(
            {
                "candidate": label,
                "candidate_kind": candidate_kind,
                "source_kind": source_kind,
                "promotion_allowed": False,
                "promotion_blocked_reason": "Package metadata is not service ownership metadata.",
                "source": _source_ref(path.name, source_line),
            }
        )
    return rows


def _string_people(
    value: object, candidate_kind: str, source_kind: str, path: Path, source_line: int | None
) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        rows.append(
            {
                "candidate": item.strip(),
                "candidate_kind": candidate_kind,
                "source_kind": source_kind,
                "promotion_allowed": False,
                "promotion_blocked_reason": "Package metadata is not service ownership metadata.",
                "source": _source_ref(path.name, source_line),
            }
        )
    return rows


def _package_json_candidates(path: Path, *, limit: int) -> list[JsonObject]:
    if limit <= 0:
        return []
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows: list[JsonObject] = []
    lines = text.splitlines()
    author_line = _line_containing_key(lines, "author")
    maintainers_line = _line_containing_key(lines, "maintainers")
    author = _package_json_person(data.get("author"))
    if author:
        rows.append(_candidate_row(author, "package_author", "package_json_author", path, author_line))
    maintainers = data.get("maintainers")
    if isinstance(maintainers, list):
        for item in maintainers:
            maintainer = _package_json_person(item)
            if maintainer:
                rows.append(_candidate_row(maintainer, "package_maintainer", "package_json_maintainers", path, maintainers_line))
            if len(rows) >= limit:
                break
    return rows[:limit]


def _package_json_person(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        return _person_label(value.get("name"), value.get("email"))
    return None


def _candidate_row(candidate: str, candidate_kind: str, source_kind: str, path: Path, line: int | None) -> JsonObject:
    return {
        "candidate": candidate,
        "candidate_kind": candidate_kind,
        "source_kind": source_kind,
        "promotion_allowed": False,
        "promotion_blocked_reason": "Package metadata is not service ownership metadata.",
        "source": _source_ref(path.name, line),
    }


def _checked_sources(repo_root: Path) -> list[JsonObject]:
    rows = []
    for relative in (
        "CODEOWNERS",
        ".github/CODEOWNERS",
        "docs/CODEOWNERS",
        "catalog-info.yaml",
        "catalog-info.yml",
        "service.yaml",
        "service.yml",
        "pyproject.toml",
        "package.json",
    ):
        rows.append({"path": relative, "exists": (repo_root / relative).is_file()})
    return rows


def _person_label(name: object, email: object) -> str:
    parts = []
    if isinstance(name, str) and name.strip():
        parts.append(name.strip())
    if isinstance(email, str) and email.strip():
        parts.append(f"<{email.strip()}>")
    return " ".join(parts)


def _line_containing_key(lines: list[str], key: str) -> int | None:
    # Best-effort citation only: parsing gives us the value, this anchors the nearest key line.
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if _line_starts_with_key(stripped, key):
            return line_number
    return None


def _line_starts_with_key(stripped_line: str, key: str) -> bool:
    return stripped_line.startswith((f"{key} ", f"{key}=", f"{key}:", f'"{key}"', f"'{key}'"))


def _source_ref(path: str, line: int | None) -> JsonObject:
    row: JsonObject = {"path": path}
    if line is not None:
        row["line_start"] = line
        row["line_end"] = line
    return row
