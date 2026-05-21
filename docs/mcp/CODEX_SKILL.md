# Codex Bettercontext Skill

Start the local MCP server:

```bash
python -m source.scripts.build_kg --repo <repo-path> --out data/kg_runs/<snapshot-name>
python -m source.scripts.mcp_server --snapshot data/kg_runs/<snapshot-name>
```

Register the MCP endpoint in Codex using the local HTTP URL printed by the server, then follow the workflow rules below.

## When To Call Bettercontext
- Planning: service, repo, symbol, package, endpoint, event, domain, or file-path questions
- Review: known changed files or changed ranges

## Tool Order
1. Planning -> `planning_context`, then ADR tools for precise follow-up
2. Coding -> ADR tools, using ambiguous-response `candidates` and per-fact `evidence`
3. Reviewing -> `review_context`, then ADR tools per returned group

## Fallback
- On `unsupported_by_current_kg`, `ambiguous`, or `partial`, state what is unknown and use host read/grep tools

## Output Rule
- Cite returned evidence rows
- Do not paste raw evidence packets wholesale
