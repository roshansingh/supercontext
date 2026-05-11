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

This first runs the public OSS extractors, then applies the private Apache/Zappa extension extractors in this directory. Use this when judging private goldset product value; use the public `source.scripts.build_multi_kg` path when judging OSS-only behavior.

The output uses the same JSONL files as the public builder (`entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, `manifest.json`) and adds `manifest.private_extensions` with extension counts and cleared public gap-coverage count. To add another private extension, add a focused extractor under `extractors/`, wire it in `build_enriched_snapshot.py`, and add a fixture test.

Run the private-enrichment tests:

```bash
python -m unittest tests.test_private_goldset_enriched_snapshot tests.test_private_goldset_apache_vhost tests.test_private_goldset_zappa
```

Generate EvidencePacket JSON from a KG snapshot:

```bash
python examples/private-goldset/run_scenario.py --snapshot data/kg_runs/latticeai_23 --out data/kg_runs/latticeai_23/product_packets.json
```

Synthesize answers from those packets using the public answer harness:

```bash
python -m source.scripts.run_goldset_answers --packets-in data/kg_runs/latticeai_23/product_packets.json --snapshot data/kg_runs/latticeai_23 --md-out docs/evaluation/LATTICEAI-GOLDSET-ANSWERS.md
```

The private scenario IDs currently implemented are `Q082`, `Q083`, `Q088`, `Q095`, `Q100`, and `Q106`.

Private extractor extensions live under `extractors/`. Because `private-goldset` contains a hyphen, do not use dotted imports that include that directory name. Load modules by file path with `importlib.util.spec_from_file_location`, or add `examples/private-goldset` to `sys.path` and import from the valid `extractors` package, for example `import extractors.apache_vhost`.
