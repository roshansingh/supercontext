# MCP Workflow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add workflow-oriented MCP support for planning and review without widening the public primitive surface beyond the existing ADR tools plus `planning_context` and `review_context`.

**As-built status:** Completed on PR #108, then superseded by installable `bettercontext-mcp` skill templates under `source/kg/product/mcp_skill_templates/` plus `bettercontext-install-mcp-skills`. Checkboxes are marked complete to reflect the shipped implementation, and this plan is retained as an implementation reference rather than an active task list.

**Architecture:** Keep the current MCP server shape and JSON-RPC flow intact. Extend `source/kg/product/mcp_tools.py` with additive metadata fields, clearer tool descriptions, and two new composition tools that only orchestrate existing `KgSnapshot` capabilities. Finish with host-facing docs that verify the current HTTP transport works end-to-end before any stdio work is considered.

**Tech Stack:** Python 3, `unittest`, JSON-RPC over the existing `http.server` MCP server, installable skill templates under `source/kg/product/mcp_skill_templates/`, evaluation docs under `docs/mcp/`

---

### File Map

**Modify**
- `source/kg/product/mcp_tools.py`
- `tests/test_mcp_tools.py`

**Create**
- `source/kg/product/mcp_skill_templates/claude/bettercontext-mcp/SKILL.md`
- `source/kg/product/mcp_skill_templates/codex/bettercontext-mcp/SKILL.md`

**Read for implementation details**
- `source/kg/query/snapshot.py`
- `source/scripts/mcp_server.py`
- `debates/5-2026-05-19-mcp-workflow-integration--planning-revi.md`

---

### Task 1: PR1 Additive Fields And Tool Descriptions

**Files:**
- Modify: `source/kg/product/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [x] **Step 1: Write the failing additive-field tests**

Add a new extension-tools constant and one assertion helper near the top of [tests/test_mcp_tools.py](tests/test_mcp_tools.py:31):

```python
EXTENSION_TOOL_NAMES: tuple[str, ...] = ()


def _assert_additive_fields(testcase: unittest.TestCase, payload: dict[str, object]) -> None:
    testcase.assertIn("coverage_warnings", payload)
    testcase.assertIn("unsupported_scopes", payload)
    testcase.assertIn("next_actions", payload)
    testcase.assertIsInstance(payload["coverage_warnings"], list)
    testcase.assertIsInstance(payload["unsupported_scopes"], list)
    testcase.assertIsInstance(payload["next_actions"], list)
```

Then extend the existing response-shape tests so they assert the additive keys on:
- `search_services`
- `get_service_brief`
- `find_callers`
- `find_callees`
- `blast_radius`
- `get_event_consumers`
- `get_event_producers`
- `deploy_blockers_for`

- [x] **Step 2: Run the focused test file and confirm the new assertions fail**

Run:

```bash
python -m unittest tests.test_mcp_tools -v
```

Expected:
- Existing tests still execute
- New additive-field assertions fail because current payloads do not contain all three keys

- [x] **Step 3: Implement additive default-field injection in `call_tool`**

Edit [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:42) so `call_tool()` normalizes every dict payload through a single helper:

```python
def _with_default_tool_metadata(payload: JsonObject) -> JsonObject:
    return {
        **payload,
        "coverage_warnings": payload.get("coverage_warnings", []),
        "unsupported_scopes": payload.get("unsupported_scopes", []),
        "next_actions": payload.get("next_actions", []),
    }


def call_tool(kg: KgSnapshot, name: str, arguments: JsonObject | None = None) -> JsonObject:
    if name not in _TOOLS:
        raise ValueError(f"Unsupported MCP tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    result = _with_default_tool_metadata(tool.handler(kg, arguments))
    return {
        **result,
        "tool": name,
    }
```

Also extend `_unsupported_by_current_kg()` in [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:189) so the refusal shape already includes the same three keys explicitly:

```python
def _unsupported_by_current_kg(tool: str, reason: str) -> JsonObject:
    return {
        "status": "unsupported_by_current_kg",
        "reason": reason,
        "missing_contract": tool,
        "coverage_warnings": [],
        "unsupported_scopes": [],
        "next_actions": [],
    }
```

- [x] **Step 4: Rewrite the 8 tool descriptions in `_TOOLS`**

Update the descriptions in [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:359) to 2-3 sentence operational descriptions. Use this exact `blast_radius` description as the anchor pattern:

```python
"blast_radius": McpTool(
    name="blast_radius",
    description=(
        "Returns downstream static CALLS closure from an anchor symbol up to `depth`. "
        "Use only when you know the exact edit-site symbol and want to enumerate intra-repo callees. "
        "Does not include reverse callers, cross-repo edges, service or endpoint boundaries, or runtime calls."
    ),
    input_schema=_object_schema(
        {**_symbol_properties(), "depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 1}},
        required=["symbol"],
    ),
    handler=_blast_radius,
)
```

Apply the same pattern to the other 7 tools: when to call, what it returns, and what it does not cover.

- [x] **Step 5: Run tests and syntax validation**

Run:

```bash
python -m unittest tests.test_mcp_tools -v
python -m compileall -q source
```

Expected:
- `tests.test_mcp_tools` passes
- `compileall` prints no output

- [x] **Step 6: Commit PR1-sized changes**

```bash
git add source/kg/product/mcp_tools.py tests/test_mcp_tools.py
git commit -m "Add MCP workflow metadata defaults"
```

---

### Task 2: PR2 Add `planning_context`

**Files:**
- Modify: `source/kg/product/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [x] **Step 1: Add failing `planning_context` schema and behavior tests**

Extend [tests/test_mcp_tools.py](tests/test_mcp_tools.py:31) with `EXTENSION_TOOL_NAMES = ("planning_context",)` and add a new test group covering:
- `tool_definitions()` includes `planning_context` after the 8 ADR names
- `planning_context` with `{"symbol": "charge_card"}` returns `status == "found"`
- `planning_context` with `{"query": "payments"}` returns `found` if exactly one resolver matches
- `planning_context` with `{"query": "handle"}` returns `ambiguous` and non-empty `next_actions`
- `planning_context` with `{}` raises a `ValueError` mentioning the required anchor set

Use this skeleton:

```python
def test_planning_context_resolves_structured_and_query_inputs(self) -> None:
    with _fixture_snapshot() as kg:
        symbol = call_tool(kg, "planning_context", {"symbol": "charge_card"})
        query = call_tool(kg, "planning_context", {"query": "payments"})

    self.assertEqual(symbol["status"], "found")
    self.assertIn("anchors", symbol)
    self.assertEqual(query["status"], "found")


def test_planning_context_ambiguous_and_empty_inputs_fail_closed(self) -> None:
    with _fixture_snapshot() as kg:
        ambiguous = call_tool(kg, "planning_context", {"query": "handle"})
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertTrue(ambiguous["next_actions"])
        with self.assertRaisesRegex(ValueError, "planning_context requires at least one of"):
            call_tool(kg, "planning_context", {})
```

- [x] **Step 2: Run the focused tests to confirm they fail**

Run:

```bash
python -m unittest tests.test_mcp_tools.McpToolsTest.test_planning_context_resolves_structured_and_query_inputs -v
python -m unittest tests.test_mcp_tools.McpToolsTest.test_planning_context_ambiguous_and_empty_inputs_fail_closed -v
```

Expected:
- Both tests fail because `planning_context` is not registered yet

- [x] **Step 3: Add helper schemas and the new tool registration**

In [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:345), add the object schema helpers needed by `planning_context`:

```python
def _planning_context_properties() -> JsonObject:
    return {
        "query": _nullable_string_schema("Optional exact identifier query when no structured anchor is known."),
        "repo": _nullable_string_schema("Repository identifier anchor."),
        "path": _nullable_string_schema("File path anchor."),
        "line": _nullable_line_schema(),
        "symbol": _nullable_string_schema("Symbol anchor."),
        "service": _nullable_string_schema("Service anchor."),
        "package": _nullable_string_schema("Package/module anchor."),
        "endpoint": _nullable_string_schema("Endpoint path anchor."),
        "event_channel": _nullable_string_schema("Event channel anchor."),
        "domain": _nullable_string_schema("Domain anchor."),
        "limit": _limit_schema(),
    }
```

Then register `planning_context` in `_TOOLS` immediately after the ADR names.

- [x] **Step 4: Implement `_planning_context` with explicit no-input validation**

Add a handler in [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:153) that:
- raises `ValueError("planning_context requires at least one of: query, repo, path, line, symbol, service, package, endpoint, event_channel, domain")` when all anchors are absent
- uses `_matching_services()` for `service`
- uses `kg.lookup_symbol()` for `symbol`
- uses `kg.repo_dependencies()` for `repo`
- uses `kg.modules_importing()` for `package`
- uses existing lexical filters for endpoint/event/domain
- builds `ambiguous` responses with `next_actions`

Use this implementation shape:

```python
def _planning_context(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    limit = _limit(arguments)
    query = _optional_string(arguments, "query")
    anchors = {
        "repo": _optional_string(arguments, "repo"),
        "path": _optional_string(arguments, "path"),
        "symbol": _optional_string(arguments, "symbol"),
        "service": _optional_string(arguments, "service"),
        "package": _optional_string(arguments, "package"),
        "endpoint": _optional_string(arguments, "endpoint"),
        "event_channel": _optional_string(arguments, "event_channel"),
        "domain": _optional_string(arguments, "domain"),
    }
    line = _optional_int(arguments, "line")
    if query is None and line is None and not any(anchors.values()):
        raise ValueError(
            "planning_context requires at least one of: query, repo, path, line, symbol, service, "
            "package, endpoint, event_channel, domain"
        )
    if anchors["symbol"]:
        symbol_result = kg.lookup_symbol(anchors["symbol"], limit=limit, path=anchors["path"], line=line)
        return _planning_context_output(
            query=query,
            anchors=anchors,
            services=[],
            symbols=[symbol_result],
            dependencies=[],
            endpoints=[],
            event_channels=[],
            domains=[],
            evidence=[],
            limit=limit,
        )
    if anchors["service"]:
        services = _matching_services(kg, anchors["service"])[:limit]
        return _planning_context_output(
            query=query,
            anchors=anchors,
            services=[_service_row(kg, row) for row in services],
            symbols=[],
            dependencies=[],
            endpoints=[],
            event_channels=[],
            domains=[],
            evidence=[],
            limit=limit,
        )
    raise ValueError("planning_context branch plan must be completed for every supported anchor type")
```

- [x] **Step 5: Add a small `_planning_context_output()` normalizer**

Return a bounded workflow response with this exact top-level shape:

```python
{
    "status": "found",
    "query": query,
    "anchors": {
        "repo": anchors.get("repo"),
        "path": anchors.get("path"),
        "symbol": anchors.get("symbol"),
        "service": anchors.get("service"),
        "package": anchors.get("package"),
        "endpoint": anchors.get("endpoint"),
        "event_channel": anchors.get("event_channel"),
        "domain": anchors.get("domain"),
    },
    "services": [],
    "symbols": [],
    "dependencies": [],
    "endpoints": [],
    "event_channels": [],
    "domains": [],
    "evidence": [],
    "coverage_warnings": [],
    "unsupported_scopes": [],
    "next_actions": [],
}
```

Keep arrays capped by `limit`; keep `evidence` capped separately at 5.

- [x] **Step 6: Run tests plus JSON-RPC integration checks**

Run:

```bash
python -m unittest tests.test_mcp_tools -v
python -m compileall -q source
```

Expected:
- `planning_context` tests pass
- Existing `tools/list` and `tools/call` JSON-RPC tests still pass

- [x] **Step 7: Commit PR2-sized changes**

```bash
git add source/kg/product/mcp_tools.py tests/test_mcp_tools.py
git commit -m "Add planning context MCP tool"
```

---

### Task 3: PR3 Add `review_context`

**Files:**
- Modify: `source/kg/product/mcp_tools.py`
- Modify: `tests/test_mcp_tools.py`

- [x] **Step 1: Write failing `review_context` definition and behavior tests**

Extend [tests/test_mcp_tools.py](tests/test_mcp_tools.py:31) so `EXTENSION_TOOL_NAMES` becomes:

```python
EXTENSION_TOOL_NAMES: tuple[str, ...] = ("planning_context", "review_context")
```

Add tests for:
- schema presence in `tool_definitions()`
- `review_context` returns `changed_symbols`, `direct_callers`, `direct_callees`, `repo_dependencies`, `coverage_warnings`, `unsupported_scopes`, `evidence`
- `include_deploy_blockers=True` yields the canonical unsupported row
- default call does not include deploy-blocker unsupported rows

Use this skeleton:

```python
def test_review_context_aggregates_symbols_and_call_edges(self) -> None:
    with _fixture_snapshot() as kg:
        result = call_tool(
            kg,
            "review_context",
            {"repo": "payments", "changed_files": ["src/checkout.py"], "limit": 10},
        )

    self.assertEqual(result["status"], "found")
    self.assertIn("changed_symbols", result)
    self.assertIn("direct_callers", result)
    self.assertIn("direct_callees", result)


def test_review_context_deploy_blocker_row_is_opt_in(self) -> None:
    with _fixture_snapshot() as kg:
        default = call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["src/checkout.py"]})
        opted_in = call_tool(
            kg,
            "review_context",
            {"repo": "payments", "changed_files": ["src/checkout.py"], "include_deploy_blockers": True},
        )

    self.assertEqual(default["unsupported_scopes"], [])
    self.assertEqual(opted_in["unsupported_scopes"][0]["kind"], "deploy_blockers")
```

- [x] **Step 2: Run the new `review_context` tests and confirm they fail**

Run:

```bash
python -m unittest tests.test_mcp_tools.McpToolsTest.test_review_context_aggregates_symbols_and_call_edges -v
python -m unittest tests.test_mcp_tools.McpToolsTest.test_review_context_deploy_blocker_row_is_opt_in -v
```

Expected:
- Fail because `review_context` does not exist yet

- [x] **Step 3: Add array/object schema helpers for changed files and ranges**

In [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:324), add:

```python
def _required_string_list(arguments: JsonObject, field: str) -> list[str]:
    value = arguments.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"MCP tool argument {field!r} must be a non-empty list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"MCP tool argument {field!r} must be a non-empty list of strings")
    return [item.strip() for item in value]


def _changed_range_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {
            "path": _string_schema("Changed file path."),
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path", "start_line", "end_line"],
        "additionalProperties": False,
    }
```

Then register `review_context` with:
- required `repo`
- required `changed_files`
- optional `changed_ranges`
- optional `limit`
- optional `include_deploy_blockers`

- [x] **Step 4: Implement `_review_context` using only existing snapshot methods**

In [source/kg/product/mcp_tools.py](source/kg/product/mcp_tools.py:153), compose:
- `kg.symbols_in_file(path, limit)`
- overlap filtering against `changed_ranges`
- `kg.find_callers(symbol_name, limit=limit, include_all=False)`
- `kg.find_callees(symbol_name, limit=limit, include_all=False)`
- `kg.repo_dependencies(repo, limit)`

Use a structure like:

```python
def _review_context(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    repo = _required_string(arguments, "repo")
    changed_files = _required_string_list(arguments, "changed_files")
    include_deploy_blockers = _optional_bool(arguments, "include_deploy_blockers", default=False)
    limit = _limit(arguments)
    changed_symbols = []
    direct_callers = []
    direct_callees = []
    repo_dependencies = kg.repo_dependencies(repo, limit=limit)
    unsupported_scopes = []
    evidence = []
    return {
        "status": "found" if changed_symbols else "not_found",
        "repo": repo,
        "changed_symbols": changed_symbols,
        "direct_callers": direct_callers,
        "direct_callees": direct_callees,
        "repo_dependencies": repo_dependencies,
        "coverage_warnings": [],
        "unsupported_scopes": unsupported_scopes,
        "evidence": evidence[:5],
        "next_actions": [],
    }
```

- [x] **Step 5: Implement the explicit deploy-blocker gate**

When `include_deploy_blockers` is `True`, append exactly:

```python
{
    "kind": "deploy_blockers",
    "scope": repo,
    "reason": "No canonical deploy-blocker relation is implemented yet",
}
```

Do not emit this row by default. Do not infer deploy intent from changed files alone.

- [x] **Step 6: Run full tests and MCP JSON-RPC checks**

Run:

```bash
python -m unittest tests.test_mcp_tools -v
python -m compileall -q source
```

Expected:
- All unit tests pass
- Existing JSON-RPC wrapper tests continue to pass with the two extension tools present

- [x] **Step 7: Commit PR3-sized changes**

```bash
git add source/kg/product/mcp_tools.py tests/test_mcp_tools.py
git commit -m "Add review context MCP tool"
```

---

### Task 4: PR4 Host Skill Docs And HTTP Verification Gate

**Files:**
- Create: `source/kg/product/mcp_skill_templates/claude/bettercontext-mcp/SKILL.md`
- Create: `source/kg/product/mcp_skill_templates/codex/bettercontext-mcp/SKILL.md`
- Create: `source/scripts/install_mcp_skills.py`

- [x] **Step 1: Create the Claude Code installable skill**

Create [SKILL.md](source/kg/product/mcp_skill_templates/claude/bettercontext-mcp/SKILL.md) with:
- setup instructions using `bettercontext-init` and `bettercontext-init --serve`
- a short “register this MCP” instruction block for Claude Code
- concise workflow rules for planning, coding, review, fallback, and evidence

- [x] **Step 2: Create the Codex installable skill**

Create [SKILL.md](source/kg/product/mcp_skill_templates/codex/bettercontext-mcp/SKILL.md) with the same concise workflow rules but Codex-specific registration wording.

- [x] **Step 3: Verify the repo still passes local checks after doc creation**

Run:

```bash
python -m compileall -q source
python -m unittest discover -s tests
```

Expected:
- `compileall` prints no output
- full test suite passes

- [x] **Step 4: Execute the HTTP verification gate before merge**

Run the local server in one terminal:

```bash
bettercontext-init --repo <repo-path>
bettercontext-mcp-server --snapshot <repo-path>/.bettercontext/kg
```

Then, from each host environment separately:
- call `tools/list`
- call `tools/call` for `planning_context`

Record pass/fail evidence in the PR description. Use this checklist in the PR body:

```md
- Claude Code HTTP MCP registration: PASS/FAIL
- Claude Code `tools/list`: PASS/FAIL
- Claude Code `planning_context`: PASS/FAIL
- Codex HTTP MCP registration: PASS/FAIL
- Codex `tools/list`: PASS/FAIL
- Codex `planning_context`: PASS/FAIL
```

If any item fails because the host cannot use the HTTP server reliably, stop and open follow-up work for `--stdio` by reusing `_handle_json_rpc_payload()` in [source/scripts/mcp_server.py](source/scripts/mcp_server.py:183). Do not merge PR4 until that transport gap is resolved or explicitly re-scoped.

- [x] **Step 5: Commit PR4-sized docs**

```bash
git add source/kg/product/mcp_skill_templates source/scripts/install_mcp_skills.py docs/mcp/HOST_SKILL_EVALUATION.md
git commit -m "Add installable Bettercontext MCP skills"
```

---

### Verification Matrix

- After Task 1: `python -m unittest tests.test_mcp_tools -v`
- After Task 2: `python -m unittest tests.test_mcp_tools -v`
- After Task 3: `python -m unittest tests.test_mcp_tools -v`
- After Task 4: `python -m unittest discover -s tests`
- After every task: `python -m compileall -q source`

### Spec Coverage Check

- Additive metadata fields: covered by Task 1
- Operational tool descriptions: covered by Task 1
- `planning_context`: covered by Task 2
- `review_context`: covered by Task 3
- Host-agent docs and HTTP verification gate: covered by Task 4
- Parked items remain out of scope: stdio, extra primitives, v2 review enrichments

### Self-Review

- No unresolved placeholders remain in this plan.
- The plan matches debate 5’s converged 4-PR scope.
- The plan keeps the visible MCP surface at 10 tools and does not reintroduce primitive promotion.
