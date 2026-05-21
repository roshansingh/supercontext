# Host Skill Evaluation

Use this checklist to evaluate whether Codex and Claude Code actually use the installed Bettercontext MCP skill during normal coding workflows.

## Setup

1. Install Bettercontext and global host-agent skills once per machine.

```bash
curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash
```

2. Build a local snapshot for the target repo.

```bash
cd <repo-path>
bettercontext-init
```

3. Start the local MCP server for that repo.

```bash
bettercontext-mcp-server --snapshot .bettercontext/kg
```

Or build and serve in one foreground command:

```bash
bettercontext-init --serve
```

4. Register the printed `/mcp` URL in the host.

Use project-local skill install only when testing repo-pinned skill behavior:

```bash
bettercontext-install-mcp-skills --scope project --project <repo-path> --agent both
```

## Evaluation Tasks

Run each task once in Codex and once in Claude Code.

### Planning

Prompt:

```text
Plan a change to <service-or-endpoint>. Before reading broadly, use Bettercontext if it can help.
```

Pass criteria:

- The agent calls `planning_context` before broad repo search.
- The call uses a structured anchor when one is available.
- The answer names returned services, symbols, dependencies, endpoints, events, or domains with evidence.
- If Bettercontext returns `ambiguous`, `not_found`, or `unsupported_by_current_kg`, the agent states the limitation before falling back.

### Coding

Prompt:

```text
Make a small safe change to <symbol-or-file>. Check caller/callee impact before editing.
```

Pass criteria:

- The agent uses `find_callers`, `find_callees`, `blast_radius`, or `planning_context` with `path`/`symbol` before editing when the anchor is known.
- The agent still reads the relevant source files before changing code.
- The agent does not claim endpoint, event, deploy, or runtime impact unless Bettercontext returned it.

### Review

Prompt:

```text
Review the current diff. Use Bettercontext for changed-file impact first, then inspect code.
```

Pass criteria:

- The agent calls `review_context` with `repo` and changed files.
- If changed ranges are available, the agent passes them.
- The review uses returned `changed_symbols`, `direct_callers`, `direct_callees`, and `repo_dependencies` to decide what to inspect.
- Findings cite evidence or file/line coordinates.

## Scoring

Score each host/task pair from 0 to 2:

- `0`: Did not use Bettercontext or used the wrong tool.
- `1`: Used Bettercontext, but late, with weak anchors, or without citing evidence.
- `2`: Used Bettercontext early, chose the right tool, cited evidence, and handled fallback honestly.

Record:

- host
- skill scope: `project` or `global`
- MCP server command and snapshot path
- prompt
- first Bettercontext tool called
- whether source reads happened before or after the MCP call
- score
- failure reason

## Interpretation

If planning scores are low, improve the skill trigger text and the `planning_context` tool description.

If coding scores are low, add more explicit examples for `find_callers`, `find_callees`, and `blast_radius`.

If review scores are low, improve changed-file/range extraction instructions and expand `review_context` output only where the KG can return supported facts.
