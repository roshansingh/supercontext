# SuperContext

SuperContext builds a typed, evidence-backed knowledge graph from local source repositories. The current v0 focuses on change-safety questions for AI coding agents and engineering teams: callers/callees, import dependencies, endpoints, event channels, deploy/config facts, and multi-repo package links.

Status: pre-1.0 local KG harness. The JSONL snapshot store, local MCP server, Streamlit evaluator UI, and validation harness are implemented. Production storage, hosted auth, PR-bot integration, and broad language coverage are still in progress.

License: TBD before public OSS release.

## Requirements

- Python 3.11 or newer.
- Node.js and `npm ci` for TypeScript/JavaScript indexing.
- Optional Python extras for specific features: `ui`, `llm`, and `agent`.

## Quickstart

Install the CLI, register the default local MCP endpoint with available host agents, and install global Codex/Claude Code MCP skills:

```bash
curl -fsSL https://raw.githubusercontent.com/roshansingh/supercontext/main/install.sh | bash
```

If you previously installed BetterContext, the installer warns about legacy `~/.bettercontext` state; remove old `bettercontext` MCP registrations and stale scripts after verifying `supercontext-init` works.

Then, inside each repo you want SuperContext to index:

```bash
supercontext-init
```

For an active local MCP server in that repo:

```bash
supercontext-init --serve
```

The install step is global because MCP registration and host-agent skills are reusable. The KG snapshot is local to each repo by default at `.supercontext/kg`.

If you need to register the local MCP endpoint manually:

```bash
supercontext-register-mcp --agent both
```

Local editable development:

```bash
python -m pip install -e .
npm ci

supercontext-init --repo /path/to/repo
supercontext-query-kg --snapshot /path/to/repo/.supercontext/kg summary
supercontext-query-kg --snapshot /path/to/repo/.supercontext/kg top-dependencies --limit 10
```

## Build A KG

Build one repo:

```bash
supercontext-build-kg \
  --repo /path/to/repo \
  --out ./data/kg_runs/example
```

Build multiple repos when repos depend on each other through package manifests:

```bash
supercontext-build-multi-kg \
  --repo /path/to/service-a \
  --repo /path/to/service-b \
  --out ./data/kg_runs/example_org
```

Use `--strict-extractors` when extractor failures should fail the build.

## Query A KG

Run common direct queries against a snapshot:

```bash
supercontext-query-kg --snapshot ./data/kg_runs/example summary
supercontext-query-kg --snapshot ./data/kg_runs/example top-dependencies --limit 10
supercontext-query-kg --snapshot ./data/kg_runs/example modules-importing pandas --limit 5
supercontext-query-kg --snapshot ./data/kg_runs/example find-callers load_model --limit 5
supercontext-query-kg --snapshot ./data/kg_runs/example endpoints --path /api/token --limit 20
```

Run multi-repo queries against a multi-repo snapshot:

```bash
supercontext-query-kg --snapshot ./data/kg_runs/example_org cross-repo-links --limit 10
supercontext-query-kg --snapshot ./data/kg_runs/example_org repo-dependencies service-b --limit 10
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

## Evaluation Traces

SuperContext evaluation code and trace-analysis skills are intended to be open and reproducible. Raw traces and repo-specific run outputs are private by default.

Local A/B harness records, downloaded LangSmith traces, SDK message streams, and intermediate deltas belong under `data/ab_runs/<run-id>/`. That path is gitignored because traces can contain prompts, final answers, file paths, snippets, model metadata, and tool-call payloads from the evaluated repo.

Checked-in evaluation reports belong under `docs/evaluation/ab-runs/<run-id>/` only when they are generated from public fixtures or have been explicitly sanitized. For private repos, keep the generated report and trace-analysis notes outside git or share only a redacted summary.

The installed host skills may include trace-evaluation guidance for Codex and Claude Code. Those skill files should describe how to analyze `ab-report.md`, `ab-report.json`, `deltas.jsonl`, and LangSmith runs, but they must not embed real trace data or customer-specific examples.

See `docs/evaluation/AB_REPRODUCTION.md` for the reproducible A/B workflow and per-run reproduction notes under `docs/evaluation/ab-runs/<run-id>/`.

## Before Open Sourcing

Remove private evaluation material before publishing this repository publicly. If any private data was committed, remove it from Git history, not only from the latest tree.

Do not publish:

- raw `data/ab_runs/` traces, SDK `messages.jsonl`, final answers, or judge reasoning
- LangSmith URLs, private run IDs, API keys, `.env`, or local machine paths
- private KG snapshots or generated artifacts from customer/org repos
- customer, org, repo, service, or file names that are not cleared for publication
- internal debates, plans, or private review notes not intended for OSS

Run the local MCP v0 server for a repo:

```bash
supercontext-init --serve
```

The server is read-only and local-development oriented. `supercontext-init --serve` is loopback-only; advanced public binds must use the MCP server directly with `--allow-public` on a trusted network.

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
