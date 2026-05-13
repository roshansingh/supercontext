# Private Goldset Examples

This directory contains private LatticeAI validation scenarios that are useful for local product validation but should not be imported from `source/`.

Build a private-enriched KG snapshot from local repos:

```bash
python examples/private-goldset/build_enriched_snapshot.py \
  --repo ~/work/orgs/latticeai/mercury_api \
  --repo ~/work/orgs/latticeai/ansible-playbooks \
  --repo ~/work/orgs/latticeai/mercury_campaign_messages \
  --out data/kg_runs/latticeai_23_private_enriched
```

This now runs the public OSS extractors through the private-goldset snapshot entry point. Apache/WSGI and Zappa event-source extraction are owned by OSS source. Keep using this command when judging private goldset product value so existing artifact paths stay stable; use the public `source.scripts.build_multi_kg` path when judging OSS-only behavior.

The output uses the same JSONL files as the public builder (`entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, `manifest.json`) and keeps `manifest.private_extensions` for compatibility. It is currently empty because no private extractors are active.

Run the private-enrichment tests:

```bash
python -m unittest tests.test_private_goldset_enriched_snapshot
```

Generate EvidencePacket JSON from a KG snapshot:

```bash
python examples/private-goldset/run_scenario.py --snapshot data/kg_runs/latticeai_23 --out data/kg_runs/latticeai_23/product_packets.json
```

Synthesize answers from those packets using the public answer harness:

```bash
python -m source.scripts.run_goldset_answers --packets-in data/kg_runs/latticeai_23/product_packets.json --snapshot data/kg_runs/latticeai_23 --md-out examples/private-goldset/LATTICEAI-GOLDSET-ANSWERS.md
```

The private scenario IDs currently implemented are `Q081`, `Q082`, `Q083`, `Q084`, `Q088`, `Q092`, `Q095`, `Q100`, and `Q106`.

There are currently no private extractor extensions. If a future private-only extractor is added, keep it out of `source/`, document why it is not OSS-generic, and add focused fixture coverage.
