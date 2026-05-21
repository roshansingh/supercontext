# BetterContext

BetterContext builds a typed, evidence-backed knowledge graph from local source repositories. The current v0 focuses on change-safety questions for AI coding agents and engineering teams: callers/callees, import dependencies, endpoints, event channels, deploy/config facts, and multi-repo package links.

Status: pre-1.0 local KG harness. The JSONL snapshot store, local MCP server, Streamlit evaluator UI, and validation harness are implemented. Production storage, hosted auth, PR-bot integration, and broad language coverage are still in progress.

License: TBD before public OSS release.

## Requirements

- Python 3.11 or newer.
- Node.js and `npm ci` for TypeScript/JavaScript indexing.
- Optional Python extras for specific features: `ui`, `llm`, and `agent`.

## Quickstart

Install the CLI and global Codex/Claude Code MCP skills:

```bash
curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash
```

Then, inside each repo you want BetterContext to index:

```bash
bettercontext-init
```

For an active local MCP server in that repo:

```bash
bettercontext-init --serve
```

The install step is global because the host-agent skills are reusable. The KG snapshot is local to each repo by default at `.bettercontext/kg`.

Local editable development:

```bash
python -m pip install -e .
npm ci

bettercontext-init --repo /path/to/repo
bettercontext-query-kg --snapshot /path/to/repo/.bettercontext/kg summary
bettercontext-query-kg --snapshot /path/to/repo/.bettercontext/kg top-dependencies --limit 10
```

## Build A KG

Build one repo:

```bash
bettercontext-build-kg \
  --repo /path/to/repo \
  --out ./data/kg_runs/example
```

Build multiple repos when repos depend on each other through package manifests:

```bash
bettercontext-build-multi-kg \
  --repo /path/to/service-a \
  --repo /path/to/service-b \
  --out ./data/kg_runs/example_org
```

Use `--strict-extractors` when extractor failures should fail the build.

## Query A KG

Run common direct queries against a snapshot:

```bash
bettercontext-query-kg --snapshot ./data/kg_runs/example summary
bettercontext-query-kg --snapshot ./data/kg_runs/example top-dependencies --limit 10
bettercontext-query-kg --snapshot ./data/kg_runs/example modules-importing pandas --limit 5
bettercontext-query-kg --snapshot ./data/kg_runs/example find-callers load_model --limit 5
bettercontext-query-kg --snapshot ./data/kg_runs/example endpoints --path /api/token --limit 20
```

Run multi-repo queries against a multi-repo snapshot:

```bash
bettercontext-query-kg --snapshot ./data/kg_runs/example_org cross-repo-links --limit 10
bettercontext-query-kg --snapshot ./data/kg_runs/example_org repo-dependencies service-b --limit 10
```

## Generate Coverage Reports

Compute coverage metrics, then render the stable JSON and Markdown report:

```bash
python -m source.scripts.coverage_metrics \
  --snapshot ./data/kg_runs/example_org \
  --expected-repos 2

python -m source.scripts.coverage_report \
  --snapshot ./data/kg_runs/example_org \
  --out docs/evaluation/runs/example-org \
  --run-id example-org \
  --tenant example \
  --expected-repos 2 \
  --metric-config source/kg/metrics/config.yaml
```

Read `coverage-run.md` for the human report and `coverage-run.json` for the machine-readable report.

Run the local MCP v0 server over an existing snapshot:

```bash
bettercontext-mcp-server --snapshot ./.bettercontext/kg --port 3845
```

The server is read-only and local-development oriented. Keep the default loopback bind unless you intentionally pass `--allow-public` on a trusted network.

## What It Extracts

- Repositories, services, modules, code symbols, imports, and static call edges.
- HTTP endpoints and client endpoint calls for supported Python and JS/TS frameworks.
- Domains, environment references, deploy/config targets, and event channels.
- Evidence rows with repo, commit, file, and line coordinates where available.
- Coverage rows for unsupported or uninstrumented known stacks.

## Repository Layout

- `source/kg/` contains the KG core, extraction, normalization, query, product-validation, and agent modules.
- `source/scripts/` contains command-line entry points.
- `tests/` contains unit, regression, drift, and packaging checks.
- `adr/` records accepted architecture decisions.
- `docs/` contains product, evaluation, review, and implementation planning docs.
- `examples/private-goldset/` contains private validation fixtures and is not part of the public product contract.

See `source/README.md` for lower-level KG module details and command examples.

## Development

```bash
python -m pip install -e ".[dev]"
npm ci
python -m compileall -q source
python -m unittest discover -s tests
```

Before changing extractors or validation behavior, rebuild the affected snapshots locally and update the relevant baseline or product-query drift artifacts only when the movement is intentional.
