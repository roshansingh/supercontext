# Host Skill Evaluation

Use this checklist to evaluate whether Codex and Claude Code actually use the installed SuperContext MCP skill during normal coding workflows.

Current product lens: SuperContext is a source-inspection head start, not a replacement for code reading. A passing host behavior uses MCP early to choose better anchors/files, then performs targeted source verification for uncovered, ambiguous, partial, compacted, or high-risk claims. Lower token or tool count is not a pass if answer quality is worse.

## Setup

1. Install SuperContext, default MCP host registration, and global host-agent skills once per machine.

```bash
curl -fsSL https://raw.githubusercontent.com/roshansingh/supercontext/main/install.sh | bash
```

If `supercontext-init` is not found after install, add the installer venv to PATH:

```bash
export PATH="$HOME/.supercontext/venv/bin:$PATH"
```

2. Build a local snapshot for the target repo.

```bash
cd <repo-path>
supercontext-init
```

3. Start the local MCP server for that repo.

```bash
supercontext-init --serve
```

4. If host registration was skipped because the Codex or Claude Code CLI was not available during install, register it after installing that host CLI.

```bash
supercontext-register-mcp --agent both
```

Use project-local skill install only when testing repo-pinned skill behavior:

```bash
supercontext-install-mcp-skills --scope project --project <repo-path> --agent both
```

## Evaluation Tasks

Run each task once in Codex and once in Claude Code.

### Planning

Prompt:

```text
Plan a change to <service-or-endpoint>. Before reading broadly, use SuperContext if it can help.
```

Pass criteria:

- The agent calls `planning_context` before broad repo search.
- The call uses a structured anchor when one is available.
- The answer names returned services, symbols, dependencies, endpoints, events, or domains with evidence.
- The agent uses `inspection_areas`, `coverage_gaps`, and any `output_budget` metadata to decide targeted follow-up reads instead of treating omitted rows as absence.
- If SuperContext returns `ambiguous`, `not_found`, or `unsupported_by_current_kg`, the agent states the limitation before falling back.

### Coding

Prompt:

```text
Make a small safe change to <symbol-or-file>. Check caller/callee impact before editing.
```

Pass criteria:

- The agent uses `find_callers`, `find_callees`, `blast_radius`, or `planning_context` with `path`/`symbol` before editing when the anchor is known.
- The agent still reads the relevant source files before changing code.
- The agent treats MCP as impact/navigation context, not permission to skip source verification.
- The agent does not claim endpoint, event, deploy, or runtime impact unless SuperContext returned it.

### Review

Prompt:

```text
Review the current diff. Use SuperContext for changed-file impact first, then inspect code.
```

Pass criteria:

- The agent calls `review_context` with `repo` and changed files.
- If changed ranges are available, the agent passes them.
- The review uses returned `changed_symbols`, `direct_callers`, `direct_callees`, and `repo_dependencies` to decide what to inspect.
- The review follows returned `inspection_areas` for missing, compacted, or candidate-only review surfaces.
- Findings cite evidence or file/line coordinates.

## Scoring

Score each host/task pair from 0 to 2:

- `0`: Did not use SuperContext or used the wrong tool.
- `1`: Used SuperContext, but late, with weak anchors, or without citing evidence.
- `2`: Used SuperContext early, chose the right tool, cited evidence, inspected targeted source where needed, and handled fallback honestly.

Record:

- host
- skill scope: `project` or `global`
- MCP server command and snapshot path
- prompt
- first SuperContext tool called
- whether source reads happened before or after the MCP call
- score
- failure reason

## Interpretation

If planning scores are low, improve the skill trigger text and the `planning_context` tool description.

If coding scores are low, add more explicit examples for `find_callers`, `find_callees`, and `blast_radius`.

If review scores are low, improve changed-file/range extraction instructions and expand `review_context` output only where the KG can return supported facts.

If scores are high on efficiency but low on quality, treat that as a product failure. Improve packet evidence, inspection guidance, tool routing, or KG extraction before claiming host-skill value.
