from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Literal


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
        return f"supercontext://{self.kind.lower()}/{stable_hash(self.identity)}"

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
