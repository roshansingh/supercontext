from __future__ import annotations

from pathlib import Path
import json
from typing import Iterable

from source.kg.core.models import Coverage, Entity, Evidence, Fact, JsonObject


class JsonlKgStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()

    def write(
        self,
        *,
        entities: Iterable[Entity],
        facts: Iterable[Fact],
        evidence: Iterable[Evidence],
        coverage: Iterable[Coverage],
        manifest: JsonObject,
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_jsonl("entities.jsonl", (entity.to_record() for entity in entities), "entity_id")
        self._write_jsonl("facts.jsonl", (fact.to_record() for fact in facts), "fact_id")
        self._write_jsonl("evidence.jsonl", (row.to_record() for row in evidence), "evidence_id")
        self._write_jsonl("coverage.jsonl", (row.to_record() for row in coverage), "coverage_id")
        self._write_json("manifest.json", manifest)

    def _write_jsonl(self, filename: str, records: Iterable[JsonObject], key: str) -> None:
        seen: set[str] = set()
        path = self.output_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                record_key = str(record[key])
                if record_key in seen:
                    continue
                seen.add(record_key)
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _write_json(self, filename: str, record: JsonObject) -> None:
        path = self.output_dir / filename
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_jsonl(path: str | Path) -> list[JsonObject]:
    records: list[JsonObject] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records
