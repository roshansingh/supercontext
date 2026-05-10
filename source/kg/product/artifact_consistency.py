from __future__ import annotations

import hashlib
import json

from source.kg.core.models import JsonObject


PACKET_FINGERPRINT_FIELDS = (
    "scenario_id",
    "user_query",
    "expected_answer_shape",
    "retrieval_steps",
    "evidence_items",
    "unknowns",
)


def packet_fingerprint(packet: JsonObject) -> str:
    """Return a stable content fingerprint for the packet material used in answer synthesis."""
    payload = {field: packet.get(field) for field in PACKET_FINGERPRINT_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
