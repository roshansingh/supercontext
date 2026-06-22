from __future__ import annotations

import unittest

from source.kg.core.models import Entity, Fact
from source.kg.query.aggregations import top_internal_dependencies


class QueryAggregationTest(unittest.TestCase):
    def test_top_internal_dependencies_excludes_resource_modules(self) -> None:
        importer = Entity(
            kind="CodeModule",
            identity={"tenant_id": "default", "repo": "web", "module": "src.App"},
        )
        code_target = Entity(
            kind="CodeModule",
            identity={"tenant_id": "default", "repo": "web", "module": "src.api"},
        )
        resource_target = Entity(
            kind="CodeModule",
            identity={"tenant_id": "default", "repo": "web", "module": "src.App.scss"},
        )
        code_import = Fact(
            predicate="IMPORTS",
            subject_id=importer.entity_id,
            object_id=code_target.entity_id,
            qualifier={"category": "internal_module", "raw_import": "./api"},
        )
        resource_import = Fact(
            predicate="IMPORTS",
            subject_id=importer.entity_id,
            object_id=resource_target.entity_id,
            qualifier={"category": "relative_resource_module", "raw_import": "./App.scss"},
        )
        entities_by_id = {
            entity.entity_id: entity.to_record()
            for entity in (importer, code_target, resource_target)
        }
        result = top_internal_dependencies(
            entities_by_id=entities_by_id,
            facts=[code_import.to_record(), resource_import.to_record()],
            evidence_by_target={},
        )

        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["results"][0]["module"], "src.api")
        self.assertEqual(result["filter"]["categories"], ["internal_module", "relative_internal_module"])


if __name__ == "__main__":
    unittest.main()
