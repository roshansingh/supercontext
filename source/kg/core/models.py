from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Literal
from urllib.parse import quote


JsonObject = dict[str, Any]
EvidenceDerivationClass = Literal[
    "authoritative_declared",
    "authoritative_static",
    "manual_override",
    "deterministic_static",
    "static_inferred",
    "candidate",
    "runtime_observed",
    "inferred_llm",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(value: JsonObject) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stable_hash(*parts: object) -> str:
    payload = "|".join(canonical_json(p) if isinstance(p, dict) else str(p) for p in parts)
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


def urn_for_kind(kind: str, identity: JsonObject) -> str:
    if kind == "Repo":
        return _structured_urn("repo", identity, ("tenant_id", "host", "owner", "name"))
    if kind == "Service":
        return _structured_urn("service", identity, ("tenant_id", "namespace", "repo", "slug"))
    if kind == "CodeModule":
        return _structured_urn("code-module", identity, ("tenant_id", "repo", "module"))
    if kind == "CodeSymbol":
        return _structured_urn("code-symbol", identity, ("tenant_id", "repo", "module", "qualname", "symbol_kind"))
    if kind == "ExternalPackage":
        return _structured_urn("external-package", identity, ("tenant_id", "repo", "name"))
    if kind == "Endpoint":
        return _endpoint_urn(identity)
    if kind == "Domain":
        return _structured_urn("domain", identity, ("tenant_id", "repo", "name"))
    if kind == "EnvVar":
        return _structured_urn("env-var", identity, ("tenant_id", "repo", "name"))
    if kind == "EventChannel":
        return _structured_urn("event-channel", identity, ("tenant_id", "broker_kind", "channel_address"))
    if kind == "DeployTarget":
        return _structured_urn("deploy-target", identity, ("tenant_id", "repo", "type", "target"))
    return _hash_urn(kind, identity)


def _endpoint_urn(identity: JsonObject) -> str:
    required = _identity_parts(identity, ("tenant_id", "repo", "protocol", "method", "path"))
    if required is None:
        return _hash_urn("Endpoint", identity)
    host = identity.get("host") or None
    host_part = "_" if host is None else _identity_part(host)
    if host_part is None:
        return _hash_urn("Endpoint", identity)
    return "supercontext://endpoint/" + "/".join((*required[:4], host_part, required[4]))


def _structured_urn(kind_slug: str, identity: JsonObject, fields: tuple[str, ...]) -> str:
    parts = _identity_parts(identity, fields)
    if parts is None:
        return _hash_urn(kind_slug, identity)
    return f"supercontext://{kind_slug}/" + "/".join(parts)


def _identity_parts(identity: JsonObject, fields: tuple[str, ...]) -> tuple[str, ...] | None:
    parts: list[str] = []
    for field_name in fields:
        part = _identity_part(identity.get(field_name))
        if part is None:
            return None
        parts.append(part)
    return tuple(parts)


def _identity_part(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return quote(stripped, safe="")


def _hash_urn(kind: str, identity: JsonObject) -> str:
    return f"supercontext://{kind.lower()}/{stable_hash(identity)}"


@dataclass(frozen=True)
class Entity:
    kind: str
    identity: JsonObject
    properties: JsonObject = field(default_factory=dict)
    canonical_status: Literal["canonical", "candidate", "demoted"] = "canonical"

    @property
    def entity_id(self) -> str:
        return f"ent_{stable_hash(self.kind, self.identity)}"

    @property
    def urn(self) -> str:
        return urn_for_kind(self.kind, self.identity)

    def to_record(self) -> JsonObject:
        record = asdict(self)
        record["entity_id"] = self.entity_id
        record["urn"] = self.urn
        return record


@dataclass(frozen=True)
class Fact:
    predicate: str
    subject_id: str
    object_id: str
    qualifier: JsonObject = field(default_factory=dict)
    canonical_status: Literal["canonical", "candidate", "demoted"] = "canonical"

    @property
    def fact_id(self) -> str:
        return f"fact_{stable_hash(self.predicate, self.subject_id, self.object_id, self.qualifier)}"

    def to_record(self) -> JsonObject:
        record = asdict(self)
        record["fact_id"] = self.fact_id
        return record


@dataclass(frozen=True)
class Evidence:
    target_type: Literal["entity", "fact"]
    target_id: str
    derivation_class: EvidenceDerivationClass
    source_system: str
    source_ref: JsonObject
    bytes_ref: JsonObject | None = None
    confidence: float | None = None
    ingested_at: str = field(default_factory=utc_now_iso)

    @property
    def evidence_id(self) -> str:
        return f"ev_{stable_hash(self.target_type, self.target_id, self.source_system, self.source_ref, self.bytes_ref)}"

    def to_record(self) -> JsonObject:
        record = asdict(self)
        record["evidence_id"] = self.evidence_id
        return record


@dataclass(frozen=True)
class Coverage:
    tenant_id: str
    predicate: str
    scope_ref: JsonObject
    state: Literal["instrumented", "partially_instrumented", "uninstrumented", "stale"]
    source_system: str
    checked_at: str = field(default_factory=utc_now_iso)

    @property
    def coverage_id(self) -> str:
        return f"cov_{stable_hash(self.tenant_id, self.predicate, self.scope_ref, self.source_system)}"

    def to_record(self) -> JsonObject:
        record = asdict(self)
        record["coverage_id"] = self.coverage_id
        return record
