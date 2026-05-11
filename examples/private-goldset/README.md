# Private Goldset Examples

This directory contains private LatticeAI validation scenarios that are useful for local product validation but should not be imported from `source/`.

Generate EvidencePacket JSON from a KG snapshot:

```bash
python examples/private-goldset/run_scenario.py --snapshot data/kg_runs/latticeai_23 --out data/kg_runs/latticeai_23/product_packets.json
```

Synthesize answers from those packets using the public answer harness:

```bash
python -m source.scripts.run_goldset_answers --packets-in data/kg_runs/latticeai_23/product_packets.json --snapshot data/kg_runs/latticeai_23 --md-out docs/evaluation/LATTICEAI-GOLDSET-ANSWERS.md
```

The private scenario IDs currently implemented are `Q082`, `Q083`, `Q088`, `Q095`, `Q100`, and `Q106`.

Private extractor extensions live under `extractors/`. Because this directory name contains a hyphen, load extension modules by file path with `importlib.util.spec_from_file_location` or from a runner that adds the directory to `sys.path`; do not use dotted package imports.
