from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from source.kg.models import JsonObject


IdentityKey = Literal["endpoint_path", "event_channel", "display_name"]
MAX_POSSIBLE_MATCH_COMPARISONS_PER_LEFT = 250


@dataclass(frozen=True)
class ContractSide:
    name: str
    predicates: tuple[str, ...]
    repos: tuple[str, ...] = ()
    path_prefix: str | None = None


@dataclass(frozen=True)
class ContractReconciliationSpec:
    name: str
    left: ContractSide
    right: ContractSide
    identity_key: IdentityKey
    possible_match_threshold: float = 0.78


def reconcile_contract(kg, spec: ContractReconciliationSpec) -> JsonObject:
    left_rows = _contract_rows(kg, spec.left, spec.identity_key)
    right_rows = _contract_rows(kg, spec.right, spec.identity_key)
    left_by_key = _rows_by_key(left_rows)
    right_by_key = _rows_by_key(right_rows)

    exact_keys = sorted(set(left_by_key) & set(right_by_key))
    left_only_keys = sorted(set(left_by_key) - set(right_by_key))
    right_only_keys = sorted(set(right_by_key) - set(left_by_key))

    possible_matches = _possible_matches(left_only_keys, right_only_keys, spec.possible_match_threshold)
    matched_left_keys = {row["left_key"] for row in possible_matches}
    matched_right_keys = {row["right_key"] for row in possible_matches}
    left_only_keys = [key for key in left_only_keys if key not in matched_left_keys]
    right_only_keys = [key for key in right_only_keys if key not in matched_right_keys]

    return {
        "status": "found" if left_rows or right_rows else "not_found",
        "spec": _spec_record(spec),
        "left_count": len(left_rows),
        "right_count": len(right_rows),
        "matched_count": len(exact_keys),
        "left_only_count": len(left_only_keys),
        "right_only_count": len(right_only_keys),
        "possible_match_count": len(possible_matches),
        "matched": [
            {
                "key": key,
                "left": left_by_key[key],
                "right": right_by_key[key],
            }
            for key in exact_keys
        ],
        "left_only": [{"key": key, "rows": left_by_key[key]} for key in left_only_keys],
        "right_only": [{"key": key, "rows": right_by_key[key]} for key in right_only_keys],
        "possible_matches": [
            {
                **match,
                "left": left_by_key[match["left_key"]],
                "right": right_by_key[match["right_key"]],
            }
            for match in possible_matches
        ],
    }


def _contract_rows(kg, side: ContractSide, identity_key: IdentityKey) -> list[JsonObject]:
    rows = []
    repo_filter = set(side.repos)
    for fact in kg.facts:
        if fact.get("predicate") not in side.predicates:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        object_ = kg.entities_by_id.get(fact["object_id"])
        if not subject or not object_:
            continue
        if repo_filter and not _row_in_repos(subject, object_, repo_filter):
            continue
        key = _identity_key(object_, identity_key)
        if side.path_prefix and not key.startswith(side.path_prefix):
            continue
        rows.append(
            {
                "key": key,
                "fact_id": fact["fact_id"],
                "predicate": fact.get("predicate"),
                "subject": _display(subject),
                "object": _display(object_),
                "subject_repo": _repo_of(subject),
                "object_repo": _repo_of(object_),
                "qualifier": fact.get("qualifier", {}),
                "evidence": kg.evidence_by_target.get(fact["fact_id"], []),
            }
        )
    return sorted(rows, key=lambda row: (row["key"], str(row["subject_repo"]), str(row["subject"])))


def _rows_by_key(rows: list[JsonObject]) -> dict[str, list[JsonObject]]:
    grouped: dict[str, list[JsonObject]] = {}
    for row in rows:
        grouped.setdefault(str(row["key"]), []).append(row)
    return grouped


def _possible_matches(left_keys: list[str], right_keys: list[str], threshold: float) -> list[JsonObject]:
    matches = []
    used_right: set[str] = set()
    for left_key in left_keys:
        candidate_keys = _candidate_match_keys(left_key, right_keys, used_right)
        candidates = [
            {
                "left_key": left_key,
                "right_key": right_key,
                "similarity": round(SequenceMatcher(None, left_key, right_key).ratio(), 3),
            }
            for right_key in candidate_keys
        ]
        candidates = [candidate for candidate in candidates if candidate["similarity"] >= threshold]
        if not candidates:
            continue
        best = max(candidates, key=lambda row: (row["similarity"], row["right_key"]))
        used_right.add(best["right_key"])
        matches.append(best)
    return sorted(matches, key=lambda row: (-row["similarity"], row["left_key"], row["right_key"]))


def _candidate_match_keys(left_key: str, right_keys: list[str], used_right: set[str]) -> list[str]:
    candidates = [right_key for right_key in right_keys if right_key not in used_right and _could_be_possible_match(left_key, right_key)]
    return sorted(candidates, key=lambda right_key: (-_cheap_match_score(left_key, right_key), right_key))[
        :MAX_POSSIBLE_MATCH_COMPARISONS_PER_LEFT
    ]


def _could_be_possible_match(left_key: str, right_key: str) -> bool:
    shorter = max(1, min(len(left_key), len(right_key)))
    longer = max(len(left_key), len(right_key))
    if shorter / longer < 0.35:
        return False
    left_segments = _key_segments(left_key)
    right_segments = _key_segments(right_key)
    return bool(left_segments & right_segments) or left_key[:4] == right_key[:4]


def _cheap_match_score(left_key: str, right_key: str) -> float:
    left_segments = _key_segments(left_key)
    right_segments = _key_segments(right_key)
    segment_overlap = len(left_segments & right_segments) / max(1, len(left_segments | right_segments))
    prefix_bonus = _common_prefix_len(left_key, right_key) / max(1, min(len(left_key), len(right_key)))
    length_ratio = min(len(left_key), len(right_key)) / max(1, max(len(left_key), len(right_key)))
    return segment_overlap + prefix_bonus + length_ratio


def _key_segments(key: str) -> set[str]:
    return {segment for segment in key.replace("_", "/").replace("-", "/").split("/") if segment and segment not in {"v1", "v2"}}


def _common_prefix_len(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def _identity_key(entity: JsonObject, identity_key: IdentityKey) -> str:
    identity = entity.get("identity", {})
    if identity_key == "endpoint_path":
        return _normalize_path(str(identity.get("path", "")))
    if identity_key == "event_channel":
        return f"{identity.get('broker_kind')}:{identity.get('name')}"
    return _display(entity)


def _normalize_path(path: str) -> str:
    value = path.strip()
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/") or "/"


def _row_in_repos(subject: JsonObject, object_: JsonObject, repos: set[str]) -> bool:
    return _repo_of(subject) in repos or _repo_of(object_) in repos


def _repo_of(entity: JsonObject) -> str | None:
    identity = entity.get("identity", {})
    properties = entity.get("properties", {})
    return identity.get("repo") or properties.get("repo")


def _display(entity: JsonObject) -> str:
    identity = entity.get("identity", {})
    kind = entity.get("kind")
    if kind == "CodeSymbol":
        return f"{identity.get('module')}.{identity.get('qualname')}"
    if kind == "CodeModule":
        return str(identity.get("module"))
    if kind == "Endpoint":
        host = identity.get("host")
        prefix = f"{host} " if host else ""
        return f"{prefix}{identity.get('method')} {identity.get('path')}"
    if kind == "EventChannel":
        return f"{identity.get('broker_kind')}:{identity.get('name')}"
    if kind == "DeployTarget":
        return f"{identity.get('type')}:{identity.get('target')}"
    if kind == "EnvVar":
        return str(identity.get("name"))
    return str(identity.get("name") or identity.get("slug") or identity)


def _spec_record(spec: ContractReconciliationSpec) -> JsonObject:
    return {
        "name": spec.name,
        "identity_key": spec.identity_key,
        "left": _side_record(spec.left),
        "right": _side_record(spec.right),
        "possible_match_threshold": spec.possible_match_threshold,
    }


def _side_record(side: ContractSide) -> JsonObject:
    return {
        "name": side.name,
        "predicates": list(side.predicates),
        "repos": list(side.repos),
        "path_prefix": side.path_prefix,
    }
