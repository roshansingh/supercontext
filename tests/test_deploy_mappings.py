from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.query.snapshot import KgSnapshot


class DeployMappingsTest(unittest.TestCase):
    def test_candidate_deploy_links_are_partitioned_from_known_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service = Entity(
                "Service",
                {"tenant_id": "default", "namespace": "default", "repo": "api", "slug": "api"},
            )
            target = Entity(
                "DeployTarget",
                {"tenant_id": "default", "repo": "ops", "type": "wsgi", "target": "/srv/app/wsgi.py"},
            )
            deploy = Fact(
                "DEPLOYS_VIA_CONFIG",
                service.entity_id,
                target.entity_id,
                {"source_kind": "runtime_linker", "resolved_by": "wsgi_ambiguous_module_path_suffix"},
                canonical_status="candidate",
            )
            JsonlKgStore(root).write(
                entities=[service, target],
                facts=[deploy],
                evidence=[
                    Evidence(
                        target_type="fact",
                        target_id=deploy.fact_id,
                        derivation_class="candidate",
                        source_system="runtime_linker",
                        source_ref={"resolved_by": "wsgi_ambiguous_module_path_suffix"},
                        bytes_ref={"repo": "ops", "path": "apache/site.conf", "line_start": 7, "line_end": 8},
                        confidence=0.5,
                    )
                ],
                coverage=[],
                manifest={"version": 1},
            )

            result = KgSnapshot(root).deploy_mappings(limit=10)

        self.assertEqual(result["mapping_count"], 0)
        self.assertEqual(result["deploy_mapping_fact_count"], 1)
        self.assertEqual(result["known_linked_count"], 0)
        self.assertEqual(result["candidate_or_unlinked_count"], 1)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["known_returned_count"], 0)
        self.assertEqual(result["candidate_returned_count"], 1)
        self.assertEqual(result["mappings"], [])
        candidate = result["candidate_or_unlinked"][0]
        self.assertEqual(candidate["predicate"], "DEPLOYS_VIA_CONFIG")
        self.assertEqual(candidate["canonical_status"], "candidate")
        self.assertEqual(candidate["linkage_status"], "candidate_or_unlinked")


if __name__ == "__main__":
    unittest.main()
