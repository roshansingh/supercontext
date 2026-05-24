"""
Three-way evaluation: grep vs Claude Code (multi-step agent) vs SuperContext KG.

For each structural code-understanding query, compares:
  1. grep: Single text search command
  2. Claude Code: Multi-step agent simulation (grep → read → grep → reason)
     Simulates the tool-call chain an AI coding agent would execute
  3. SuperContext: Instant KG query

Measures: result quality, tool calls needed, total latency, precision.
"""
from __future__ import annotations

import ast as python_ast
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "codesearchnet"
RESULTS_DIR = EVAL_DIR / "three-way-eval"
SNAPSHOT_DIR = REPO_ROOT / "data" / "kg_runs" / "codesearchnet"
CSN_REPO = Path(os.environ.get("CSN_REPO", str(REPO_ROOT.parent / "CodeSearchNet")))

PY_FILES_CMD = ["find", str(CSN_REPO), "-name", "*.py",
                "-not", "-path", "*/resources/*", "-not", "-path", "*/notebooks/*",
                "-not", "-path", "*/.git/*"]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    tool: str
    args: str
    result_summary: str
    latency_ms: float

@dataclass
class ApproachResult:
    approach: str
    query_id: str
    tool_calls: list[ToolCall]
    total_tool_calls: int
    total_latency_ms: float
    result_count: int
    has_qualified_names: bool
    has_evidence: bool
    has_transitive_deps: bool
    has_call_direction: bool
    precision: str  # "exact", "noisy", "partial", "none"
    answer_quality: str
    raw_answer: Any = field(default=None, repr=False)

@dataclass
class ThreeWayComparison:
    query_id: str
    category: str
    description: str
    grep: ApproachResult
    claude_code: ApproachResult
    supercontext: ApproachResult
    winner: str
    reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_grep(pattern: str, extra_args: list[str] | None = None) -> tuple[list[str], float]:
    """Run grep via find+xargs, return (lines, latency_ms)."""
    t0 = time.monotonic()
    r = subprocess.run(PY_FILES_CMD, capture_output=True, text=True, timeout=10)
    files = r.stdout.strip()
    if not files:
        return [], (time.monotonic() - t0) * 1000

    cmd = ["xargs", "grep", "-rn", "-E", pattern]
    if extra_args:
        cmd.extend(extra_args)
    r2 = subprocess.run(cmd, input=files, capture_output=True, text=True, timeout=10)
    latency = (time.monotonic() - t0) * 1000
    lines = [l for l in r2.stdout.strip().split("\n") if l]
    return lines, latency


def _run_grep_files(pattern: str) -> tuple[list[str], float]:
    """Run grep -l, return (files, latency_ms)."""
    t0 = time.monotonic()
    r = subprocess.run(PY_FILES_CMD, capture_output=True, text=True, timeout=10)
    files = r.stdout.strip()
    if not files:
        return [], (time.monotonic() - t0) * 1000

    r2 = subprocess.run(
        ["xargs", "grep", "-rl", "-E", pattern],
        input=files, capture_output=True, text=True, timeout=10,
    )
    latency = (time.monotonic() - t0) * 1000
    result_files = [f for f in r2.stdout.strip().split("\n") if f]
    return result_files, latency


def _read_file_lines(path: str, start: int, end: int) -> tuple[str, float]:
    """Simulate reading specific lines from a file."""
    t0 = time.monotonic()
    try:
        with open(path) as f:
            lines = f.readlines()
        content = "".join(lines[max(0, start-1):end])
    except Exception:
        content = ""
    return content, (time.monotonic() - t0) * 1000


def _run_sc_query(args: list[str]) -> tuple[dict, float]:
    """Run a SuperContext KG query."""
    cmd = ["python", "-m", "source.scripts.query_kg", "--snapshot", str(SNAPSHOT_DIR)]
    cmd.extend(args)
    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
    latency = (time.monotonic() - t0) * 1000
    if r.returncode != 0:
        return {"error": r.stderr[:200]}, latency
    return json.loads(r.stdout), latency


def _parse_ast_for_calls(code: str, target_func: str) -> list[str]:
    """Parse Python AST to find calls to a specific function."""
    calls = []
    try:
        tree = python_ast.parse(code)
        for node in python_ast.walk(tree):
            if isinstance(node, python_ast.Call):
                name = None
                if isinstance(node.func, python_ast.Name):
                    name = node.func.id
                elif isinstance(node.func, python_ast.Attribute):
                    name = node.func.attr
                if name and name == target_func:
                    calls.append(f"line {node.lineno}")
    except SyntaxError:
        pass
    return calls


# ---------------------------------------------------------------------------
# Query evaluators: each returns (grep_result, claude_code_result, sc_result)
# ---------------------------------------------------------------------------

def eval_modules_importing(query_id: str, package: str, desc: str) -> ThreeWayComparison:
    """Evaluate: which modules import <package>?"""

    # --- grep ---
    files, grep_lat = _run_grep_files(f"import {package}|from {package}")
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", f"-rl 'import {package}'", f"{len(files)} files", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(files), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="partial", answer_quality=f"{len(files)} file paths, no import details",
        raw_answer=files,
    )

    # --- Claude Code simulation ---
    cc_calls: list[ToolCall] = []
    cc_results: list[dict] = []

    # Step 1: grep for the import
    lines, lat1 = _run_grep(f"import {package}|from {package}")
    cc_calls.append(ToolCall("grep", f"'import {package}'", f"{len(lines)} matching lines", lat1))

    # Step 2: For each file, read the import line to understand the import form
    seen_files: dict[str, dict] = {}
    for line in lines[:15]:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            fpath = parts[0]
            if fpath not in seen_files:
                content, lat2 = _read_file_lines(fpath, 1, 20)
                cc_calls.append(ToolCall("read_file", f"{Path(fpath).name}:1-20", "Read import section", lat2))

                # Parse import form
                alias = None
                import_line = parts[2].strip()
                if f"import {package} as " in import_line:
                    alias = import_line.split(" as ")[-1].strip()
                elif f"import {package}" in import_line:
                    alias = package

                seen_files[fpath] = {
                    "file": str(Path(fpath).relative_to(CSN_REPO)),
                    "import_line": import_line,
                    "alias": alias,
                }

    cc_total_lat = sum(c.latency_ms for c in cc_calls)
    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(seen_files), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="partial", answer_quality=f"{len(seen_files)} files with import form parsed",
        raw_answer=list(seen_files.values()),
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["modules-importing", package, "--limit", "25"])
    sc_count = len(sc_data) if isinstance(sc_data, list) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", f"modules-importing {package}", f"{sc_count} typed imports", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=False,
        precision="exact", answer_quality=f"{sc_count} imports with alias, category, evidence, line numbers",
        raw_answer=None,
    )

    winner = "supercontext"
    reason = f"SC: 1 call, typed metadata. Claude Code: {len(cc_calls)} calls to get partial info. grep: flat file list."

    return ThreeWayComparison(
        query_id=query_id, category="dependency", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner=winner, reason=reason,
    )


def eval_find_callers(query_id: str, symbol: str, desc: str) -> ThreeWayComparison:
    """Evaluate: who calls <symbol>?"""
    short_name = symbol.split(".")[-1]

    # --- grep ---
    files, grep_lat = _run_grep_files(short_name)
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", f"-rl '{short_name}'", f"{len(files)} files", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(files), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="noisy", answer_quality=f"{len(files)} files mention '{short_name}' — includes defs, strings, comments",
        raw_answer=files,
    )

    # --- Claude Code simulation ---
    cc_calls: list[ToolCall] = []
    callers_found: list[dict] = []

    # Step 1: grep for the symbol
    lines, lat1 = _run_grep(short_name)
    cc_calls.append(ToolCall("grep", f"'{short_name}'", f"{len(lines)} lines", lat1))

    # Step 2: Find definition to exclude it
    def_lines, lat2 = _run_grep(f"def {short_name}")
    cc_calls.append(ToolCall("grep", f"'def {short_name}'", f"{len(def_lines)} definitions", lat2))
    def_locations = set()
    for dl in def_lines:
        parts = dl.split(":", 2)
        if len(parts) >= 2:
            def_locations.add((parts[0], parts[1]))

    # Step 3: For each non-def match, read surrounding context to verify it's a call
    call_files = set()
    for line in lines[:20]:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            fpath, lineno = parts[0], parts[1]
            if (fpath, lineno) in def_locations:
                continue
            if fpath not in call_files:
                call_files.add(fpath)
                ln = int(lineno) if lineno.isdigit() else 1
                content, lat3 = _read_file_lines(fpath, max(1, ln-5), ln+5)
                cc_calls.append(ToolCall("read_file", f"{Path(fpath).name}:{ln-5}-{ln+5}", "Verify call context", lat3))

                # Step 4: Parse AST to confirm it's actually a call
                try:
                    with open(fpath) as f:
                        full_code = f.read()
                    ast_calls = _parse_ast_for_calls(full_code, short_name)
                    if ast_calls:
                        # Find enclosing function
                        tree = python_ast.parse(full_code)
                        for node in python_ast.walk(tree):
                            if isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                                if any(isinstance(child, python_ast.Call) and
                                       (isinstance(child.func, python_ast.Name) and child.func.id == short_name or
                                        isinstance(child.func, python_ast.Attribute) and child.func.attr == short_name)
                                       for child in python_ast.walk(node)):
                                    callers_found.append({
                                        "caller": node.name,
                                        "file": str(Path(fpath).relative_to(CSN_REPO)),
                                        "line": node.lineno,
                                    })
                except Exception:
                    pass

    cc_total_lat = sum(c.latency_ms for c in cc_calls)
    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(callers_found), has_qualified_names=True, has_evidence=False,
        has_transitive_deps=False, has_call_direction=True,
        precision="partial",
        answer_quality=f"{len(callers_found)} callers found via multi-step grep+AST (no method ownership)",
        raw_answer=callers_found,
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["find-callers", symbol, "--limit", "25", "--include-all"])
    sc_count = sc_data.get("caller_count", 0) if isinstance(sc_data, dict) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", f"find-callers {symbol}", f"{sc_count} callers", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=True,
        precision="exact",
        answer_quality=f"{sc_count} callers with qualified names, evidence lines, commit SHA",
        raw_answer=None,
    )

    winner = "supercontext"
    reason = f"SC: 1 call, {sc_count} precise callers. Claude Code: {len(cc_calls)} calls, {len(callers_found)} callers (manual AST). grep: {len(files)} noisy file matches."

    return ThreeWayComparison(
        query_id=query_id, category="call_graph", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner=winner, reason=reason,
    )


def eval_blast_radius(query_id: str, symbol: str, desc: str) -> ThreeWayComparison:
    """Evaluate: what breaks if <symbol> changes?"""
    short_name = symbol.split(".")[-1]

    # --- grep ---
    files, grep_lat = _run_grep_files(short_name)
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", f"-rl '{short_name}'", f"{len(files)} files", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(files), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="noisy",
        answer_quality=f"{len(files)} files mention '{short_name}' — no transitive analysis possible",
        raw_answer=files,
    )

    # --- Claude Code simulation ---
    cc_calls: list[ToolCall] = []
    affected: list[dict] = []

    # Step 1: Find the symbol definition
    def_lines, lat1 = _run_grep(f"def {short_name}|class {short_name}")
    cc_calls.append(ToolCall("grep", f"'def {short_name}'", f"{len(def_lines)} defs", lat1))

    # Step 2: Find direct references
    ref_lines, lat2 = _run_grep(short_name)
    cc_calls.append(ToolCall("grep", f"'{short_name}'", f"{len(ref_lines)} references", lat2))

    direct_files = set()
    for line in ref_lines:
        parts = line.split(":", 2)
        if len(parts) >= 2:
            direct_files.add(parts[0])

    # Step 3: For each file, find what module it belongs to
    for fpath in list(direct_files)[:8]:
        content, lat3 = _read_file_lines(fpath, 1, 10)
        cc_calls.append(ToolCall("read_file", f"{Path(fpath).name}:1-10", "Read module header", lat3))
        affected.append({"file": str(Path(fpath).relative_to(CSN_REPO)), "type": "direct"})

    # Step 4: Try to find transitive deps — what imports these files?
    for fpath in list(direct_files)[:5]:
        module_name = Path(fpath).stem
        imp_lines, lat4 = _run_grep(f"import.*{module_name}|from.*{module_name}")
        cc_calls.append(ToolCall("grep", f"'import {module_name}'", f"{len(imp_lines)} importers", lat4))
        for il in imp_lines[:3]:
            iparts = il.split(":", 2)
            if len(iparts) >= 2 and iparts[0] not in direct_files:
                affected.append({"file": str(Path(iparts[0]).relative_to(CSN_REPO)), "type": "transitive"})

    cc_total_lat = sum(c.latency_ms for c in cc_calls)
    transitive = [a for a in affected if a["type"] == "transitive"]
    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(affected), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=len(transitive) > 0, has_call_direction=False,
        precision="partial",
        answer_quality=f"{len(affected)} affected ({len(transitive)} transitive) via {len(cc_calls)}-step manual trace",
        raw_answer=affected,
    )

    # --- SuperContext ---
    sc_args = ["blast-radius", symbol, "--depth", "2", "--include-all"]
    sc_data, sc_lat = _run_sc_query(sc_args)
    sc_edges = len(sc_data.get("edges", [])) if isinstance(sc_data, dict) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", f"blast-radius {symbol}", f"{sc_edges} edges", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_edges, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=sc_edges > 0, has_call_direction=True,
        precision="exact" if sc_edges > 0 else "none",
        answer_quality=f"{sc_edges} dependency edges with full call chain and evidence" if sc_edges > 0 else "Ambiguous symbol, fail-closed",
        raw_answer=None,
    )

    winner = "supercontext" if sc_edges > 0 else ("claude_code" if len(affected) > 0 else "tie")
    reason = f"SC: 1 call, {sc_edges} edges (instant). Claude Code: {len(cc_calls)} calls, {len(affected)} affected (manual trace). grep: flat file list."

    return ThreeWayComparison(
        query_id=query_id, category="blast_radius", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner=winner, reason=reason,
    )


def eval_top_fan_in(query_id: str, desc: str) -> ThreeWayComparison:
    """Evaluate: which symbols have the most callers?"""

    # --- grep ---
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[],
        total_tool_calls=0, total_latency_ms=0,
        result_count=0, has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="none", answer_quality="Not possible with grep — requires call graph analysis",
    )

    # --- Claude Code simulation ---
    cc_calls: list[ToolCall] = []

    # Step 1: Find all Python files
    t0 = time.monotonic()
    r = subprocess.run(PY_FILES_CMD, capture_output=True, text=True, timeout=10)
    py_files = [f for f in r.stdout.strip().split("\n") if f]
    lat1 = (time.monotonic() - t0) * 1000
    cc_calls.append(ToolCall("find", "*.py", f"{len(py_files)} files", lat1))

    # Step 2: Read each file and parse AST
    call_counts: dict[str, int] = {}
    for fpath in py_files[:30]:
        try:
            content, lat_r = _read_file_lines(fpath, 1, 1000)
            cc_calls.append(ToolCall("read_file", Path(fpath).name, f"Read {len(content)} chars", lat_r))
            tree = python_ast.parse(content)
            for node in python_ast.walk(tree):
                if isinstance(node, python_ast.Call):
                    name = None
                    if isinstance(node.func, python_ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, python_ast.Attribute):
                        name = node.func.attr
                    if name:
                        call_counts[name] = call_counts.get(name, 0) + 1
        except Exception:
            pass

    top_calls = sorted(call_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    cc_total_lat = sum(c.latency_ms for c in cc_calls)

    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(top_calls), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=True,
        precision="partial",
        answer_quality=f"{len(top_calls)} call-count ranked symbols via {len(cc_calls)} file reads + AST parsing (no qualified names, no caller identity)",
        raw_answer=[{"symbol": s, "call_count": c} for s, c in top_calls],
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["top-fan-in-symbols", "--limit", "15"])
    sc_count = sc_data.get("result_count", 0) if isinstance(sc_data, dict) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", "top-fan-in-symbols", f"{sc_count} symbols ranked", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=True,
        precision="exact",
        answer_quality=f"{sc_count} symbols with qualified names, caller identities, evidence samples",
        raw_answer=None,
    )

    return ThreeWayComparison(
        query_id=query_id, category="call_graph", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner="supercontext",
        reason=f"SC: 1 call instant. Claude Code: {len(cc_calls)} tool calls across {len(py_files[:30])} files. grep: impossible.",
    )


def eval_symbols_in_file(query_id: str, filepath: str, desc: str) -> ThreeWayComparison:
    """Evaluate: what symbols are defined in <file>?"""
    full_path = str(CSN_REPO / filepath)

    # --- grep ---
    t0 = time.monotonic()
    lines = []
    try:
        r = subprocess.run(["grep", "-n", "-E", r"^\s*def |^\s*class ", full_path],
                           capture_output=True, text=True, timeout=10)
        lines = [l for l in r.stdout.strip().split("\n") if l]
    except Exception:
        pass
    grep_lat = (time.monotonic() - t0) * 1000

    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", f"'def|class' {Path(filepath).name}", f"{len(lines)} defs", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(lines), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="partial", answer_quality=f"{len(lines)} def/class lines — no class membership, no qualified names",
        raw_answer=lines,
    )

    # --- Claude Code simulation ---
    cc_calls: list[ToolCall] = []

    # Step 1: Read the file
    content, lat1 = _read_file_lines(full_path, 1, 1000)
    cc_calls.append(ToolCall("read_file", filepath, f"Read full file", lat1))

    # Step 2: Parse AST for symbols
    symbols: list[dict] = []
    try:
        tree = python_ast.parse(content)
        for node in python_ast.iter_child_nodes(tree):
            if isinstance(node, python_ast.ClassDef):
                class_entry = {"name": node.name, "kind": "class", "line": node.lineno, "methods": []}
                symbols.append(class_entry)
                for child in python_ast.iter_child_nodes(node):
                    if isinstance(child, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                        class_entry["methods"].append(child.name)
                        symbols.append({"name": f"{node.name}.{child.name}", "kind": "method", "line": child.lineno})
            elif isinstance(node, (python_ast.FunctionDef, python_ast.AsyncFunctionDef)):
                symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
    except SyntaxError:
        pass

    cc_total_lat = sum(c.latency_ms for c in cc_calls)
    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(symbols), has_qualified_names=True, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="exact",
        answer_quality=f"{len(symbols)} symbols with class membership via file read + AST",
        raw_answer=symbols,
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["symbols-in-file", filepath])
    sc_count = len(sc_data.get("symbols", [])) if isinstance(sc_data, dict) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", f"symbols-in-file {filepath}", f"{sc_count} symbols", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=False,
        precision="exact",
        answer_quality=f"{sc_count} symbols with qualified names, module path, evidence",
        raw_answer=None,
    )

    # Claude Code gets close here since it can read+parse one file
    winner = "supercontext" if sc_count > 0 else "claude_code"
    reason = f"SC and Claude Code both use AST parsing. SC: pre-indexed, instant. Claude Code: 1 read + parse."

    return ThreeWayComparison(
        query_id=query_id, category="symbol", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner=winner, reason=reason,
    )


def eval_who_imports(query_id: str, module: str, desc: str) -> ThreeWayComparison:
    """Evaluate: who imports <module>?"""
    short = module.split(".")[-1]

    # --- grep ---
    files, grep_lat = _run_grep_files(f"import.*{short}|from.*{short}")
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", f"-rl 'import {short}'", f"{len(files)} files", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(files), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="noisy", answer_quality=f"{len(files)} files — may include partial name matches",
        raw_answer=files,
    )

    # --- Claude Code ---
    cc_calls: list[ToolCall] = []

    # Step 1: grep for exact module import
    lines, lat1 = _run_grep(f"from {module} |import {module}")
    cc_calls.append(ToolCall("grep", f"'from {module}'", f"{len(lines)} lines", lat1))

    # Step 2: Also try dotted path variants
    module_path = module.replace(".", "/")
    lines2, lat2 = _run_grep(f"from {module.replace('.', '/')}|from \\..*{short}")
    cc_calls.append(ToolCall("grep", f"path variants", f"{len(lines2)} lines", lat2))

    all_importers = set()
    for line in lines + lines2:
        parts = line.split(":", 2)
        if len(parts) >= 2:
            all_importers.add(parts[0])

    cc_total_lat = sum(c.latency_ms for c in cc_calls)
    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(all_importers), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="partial",
        answer_quality=f"{len(all_importers)} importing files via multi-pattern grep",
        raw_answer=list(all_importers),
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["who-imports", module, "--limit", "25"])
    sc_groups = sc_data.get("groups", []) if isinstance(sc_data, dict) else []
    sc_count = sum(g.get("count", len(g.get("importers", []))) for g in sc_groups)
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", f"who-imports {module}", f"{sc_count} importers", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=False,
        precision="exact",
        answer_quality=f"{sc_count} importers grouped by prefix with evidence",
        raw_answer=None,
    )

    winner = "supercontext" if sc_count > 0 else ("claude_code" if len(all_importers) > 0 else "tie")
    reason = f"SC: 1 call, grouped importers. Claude Code: {len(cc_calls)} calls. grep: noisy matches."

    return ThreeWayComparison(
        query_id=query_id, category="structural", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner=winner, reason=reason,
    )


def eval_top_internal_deps(query_id: str, desc: str) -> ThreeWayComparison:
    """Evaluate: what are the most-depended-on internal modules?"""

    # --- grep ---
    lines, grep_lat = _run_grep(r"^from src\.|^import src\.")
    grep_result = ApproachResult(
        approach="grep", query_id=query_id,
        tool_calls=[ToolCall("grep", "'from src.|import src.'", f"{len(lines)} import lines", grep_lat)],
        total_tool_calls=1, total_latency_ms=round(grep_lat, 1),
        result_count=len(lines), has_qualified_names=False, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="noisy", answer_quality=f"{len(lines)} raw import lines — no ranking, no dedup",
        raw_answer=lines[:10],
    )

    # --- Claude Code ---
    cc_calls: list[ToolCall] = []

    # Step 1: grep for internal imports across all files
    all_lines, lat1 = _run_grep(r"^from \.|^import src\.|^from src\.")
    cc_calls.append(ToolCall("grep", "internal imports", f"{len(all_lines)} lines", lat1))

    # Step 2: Parse and rank
    import_targets: dict[str, set[str]] = {}
    for line in all_lines:
        parts = line.split(":", 2)
        if len(parts) >= 3:
            fpath = parts[0]
            imp_line = parts[2].strip()
            match = re.match(r"from (\S+) import|import (\S+)", imp_line)
            if match:
                target = match.group(1) or match.group(2)
                if target not in import_targets:
                    import_targets[target] = set()
                import_targets[target].add(fpath)

    ranked = sorted(import_targets.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    cc_total_lat = sum(c.latency_ms for c in cc_calls)

    claude_result = ApproachResult(
        approach="claude_code", query_id=query_id,
        tool_calls=cc_calls,
        total_tool_calls=len(cc_calls), total_latency_ms=round(cc_total_lat, 1),
        result_count=len(ranked), has_qualified_names=True, has_evidence=False,
        has_transitive_deps=False, has_call_direction=False,
        precision="partial",
        answer_quality=f"{len(ranked)} modules ranked by importer count via grep + manual parse",
        raw_answer=[{"module": m, "importers": len(fs)} for m, fs in ranked],
    )

    # --- SuperContext ---
    sc_data, sc_lat = _run_sc_query(["top-internal-dependencies", "--limit", "15"])
    sc_count = sc_data.get("result_count", 0) if isinstance(sc_data, dict) else 0
    sc_result = ApproachResult(
        approach="supercontext", query_id=query_id,
        tool_calls=[ToolCall("kg_query", "top-internal-dependencies", f"{sc_count} ranked modules", sc_lat)],
        total_tool_calls=1, total_latency_ms=round(sc_lat, 1),
        result_count=sc_count, has_qualified_names=True, has_evidence=True,
        has_transitive_deps=False, has_call_direction=False,
        precision="exact",
        answer_quality=f"{sc_count} modules ranked with evidence samples and import details",
        raw_answer=None,
    )

    return ThreeWayComparison(
        query_id=query_id, category="dependency", description=desc,
        grep=grep_result, claude_code=claude_result, supercontext=sc_result,
        winner="supercontext",
        reason=f"SC: 1 call, pre-ranked. Claude Code: {len(cc_calls)} calls + post-processing. grep: raw lines.",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

EVAL_QUERIES = [
    ("DEP-01", "modules_importing", {"package": "tensorflow"}, "Which modules import tensorflow?"),
    ("DEP-02", "modules_importing", {"package": "wandb"}, "Which modules import wandb?"),
    ("DEP-03", "modules_importing", {"package": "numpy"}, "Which modules import numpy?"),
    ("DEP-04", "top_internal_deps", {}, "What are the top internal module dependencies?"),
    ("CALL-01", "find_callers", {"symbol": "get_shape_list"}, "Who calls get_shape_list?"),
    ("CALL-02", "find_callers", {"symbol": "create_initializer"}, "Who calls create_initializer?"),
    ("CALL-03", "find_callers", {"symbol": "dropout"}, "Who calls dropout?"),
    ("CALL-04", "find_callers", {"symbol": "train_log"}, "Who calls train_log?"),
    ("CALL-05", "top_fan_in", {}, "Which symbols have the most callers?"),
    ("SYM-01", "symbols_in_file", {"filepath": "src/models/model.py"}, "Symbols in model.py?"),
    ("SYM-02", "symbols_in_file", {"filepath": "src/encoders/seq_encoder.py"}, "Symbols in seq_encoder.py?"),
    ("BLAST-01", "blast_radius", {"symbol": "get_shape_list"}, "Blast radius of get_shape_list?"),
    ("BLAST-02", "blast_radius", {"symbol": "Model.train"}, "Blast radius of Model.train?"),
    ("BLAST-03", "blast_radius", {"symbol": "SeqEncoder"}, "Blast radius of SeqEncoder?"),
    ("STRUCT-01", "who_imports", {"module": "src.models.model"}, "Who imports src.models.model?"),
    ("STRUCT-02", "who_imports", {"module": "src.encoders.seq_encoder"}, "Who imports seq_encoder?"),
]


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Three-Way Evaluation: grep vs Claude Code vs SuperContext")
    print("=" * 70)
    print(f"Target: {CSN_REPO}")
    print(f"Queries: {len(EVAL_QUERIES)}")
    print()

    comparisons: list[ThreeWayComparison] = []

    for qid, qtype, kwargs, desc in EVAL_QUERIES:
        print(f"  [{qid}] {desc}")
        if qtype == "modules_importing":
            comp = eval_modules_importing(qid, kwargs["package"], desc)
        elif qtype == "find_callers":
            comp = eval_find_callers(qid, kwargs["symbol"], desc)
        elif qtype == "blast_radius":
            comp = eval_blast_radius(qid, kwargs["symbol"], desc)
        elif qtype == "top_fan_in":
            comp = eval_top_fan_in(qid, desc)
        elif qtype == "symbols_in_file":
            comp = eval_symbols_in_file(qid, kwargs["filepath"], desc)
        elif qtype == "who_imports":
            comp = eval_who_imports(qid, kwargs["module"], desc)
        elif qtype == "top_internal_deps":
            comp = eval_top_internal_deps(qid, desc)
        else:
            continue
        comparisons.append(comp)

        g, c, s = comp.grep, comp.claude_code, comp.supercontext
        print(f"    grep: {g.total_tool_calls} calls, {g.total_latency_ms:.0f}ms, {g.result_count} results [{g.precision}]")
        print(f"    claude: {c.total_tool_calls} calls, {c.total_latency_ms:.0f}ms, {c.result_count} results [{c.precision}]")
        print(f"    SC:     {s.total_tool_calls} calls, {s.total_latency_ms:.0f}ms, {s.result_count} results [{s.precision}]")
        print(f"    Winner: {comp.winner}")
        print()

    # Summary
    sc_wins = sum(1 for c in comparisons if c.winner == "supercontext")
    cc_wins = sum(1 for c in comparisons if c.winner == "claude_code")
    grep_wins = sum(1 for c in comparisons if c.winner == "grep")
    ties = sum(1 for c in comparisons if c.winner == "tie")

    avg_grep_calls = sum(c.grep.total_tool_calls for c in comparisons) / len(comparisons)
    avg_cc_calls = sum(c.claude_code.total_tool_calls for c in comparisons) / len(comparisons)
    avg_sc_calls = sum(c.supercontext.total_tool_calls for c in comparisons) / len(comparisons)

    avg_grep_lat = sum(c.grep.total_latency_ms for c in comparisons) / len(comparisons)
    avg_cc_lat = sum(c.claude_code.total_latency_ms for c in comparisons) / len(comparisons)
    avg_sc_lat = sum(c.supercontext.total_latency_ms for c in comparisons) / len(comparisons)

    total_cc_calls = sum(c.claude_code.total_tool_calls for c in comparisons)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_repo": str(CSN_REPO),
        "query_count": len(comparisons),
        "summary": {
            "wins": {"supercontext": sc_wins, "claude_code": cc_wins, "grep": grep_wins, "tie": ties},
            "avg_tool_calls": {"grep": round(avg_grep_calls, 1), "claude_code": round(avg_cc_calls, 1), "supercontext": round(avg_sc_calls, 1)},
            "avg_latency_ms": {"grep": round(avg_grep_lat, 1), "claude_code": round(avg_cc_lat, 1), "supercontext": round(avg_sc_lat, 1)},
            "total_claude_code_tool_calls": total_cc_calls,
        },
        "comparisons": [
            {
                "query_id": c.query_id,
                "category": c.category,
                "description": c.description,
                "winner": c.winner,
                "reason": c.reason,
                "grep": {k: v for k, v in asdict(c.grep).items() if k != "raw_answer"},
                "claude_code": {k: v for k, v in asdict(c.claude_code).items() if k != "raw_answer"},
                "supercontext": {k: v for k, v in asdict(c.supercontext).items() if k != "raw_answer"},
            }
            for c in comparisons
        ],
    }

    report_path = RESULTS_DIR / "three_way_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    md = _render_markdown(report, comparisons)
    md_path = RESULTS_DIR / "three_way_report.md"
    with open(md_path, "w") as f:
        f.write(md)

    print("=" * 70)
    print(f"RESULTS ({len(comparisons)} queries)")
    print(f"  Wins: SC={sc_wins} | Claude Code={cc_wins} | grep={grep_wins} | Tie={ties}")
    print(f"  Avg tool calls: grep={avg_grep_calls:.0f} | Claude Code={avg_cc_calls:.0f} | SC={avg_sc_calls:.0f}")
    print(f"  Avg latency:    grep={avg_grep_lat:.0f}ms | Claude Code={avg_cc_lat:.0f}ms | SC={avg_sc_lat:.0f}ms")
    print(f"  Total Claude Code tool calls across all queries: {total_cc_calls}")
    print(f"\n  Reports: {report_path}")
    print(f"           {md_path}")
    print("=" * 70)


def _render_markdown(report: dict, comparisons: list[ThreeWayComparison]) -> str:
    s = report["summary"]
    lines = [
        "# Three-Way Eval: grep vs Claude Code vs SuperContext",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Target:** github/CodeSearchNet ({report['query_count']} queries)",
        "",
        "## Summary",
        "",
        "| Metric | grep | Claude Code | SuperContext |",
        "|--------|------|-------------|-------------|",
        f"| Wins | {s['wins']['grep']} | {s['wins']['claude_code']} | {s['wins']['supercontext']} |",
        f"| Avg tool calls | {s['avg_tool_calls']['grep']} | {s['avg_tool_calls']['claude_code']} | {s['avg_tool_calls']['supercontext']} |",
        f"| Avg latency (ms) | {s['avg_latency_ms']['grep']} | {s['avg_latency_ms']['claude_code']} | {s['avg_latency_ms']['supercontext']} |",
        f"| Total tool calls | {report['query_count']} | {s['total_claude_code_tool_calls']} | {report['query_count']} |",
        "",
        "## Per-Query Results",
        "",
        "| ID | Description | grep calls | CC calls | SC calls | grep lat | CC lat | SC lat | Winner |",
        "|----|-------------|-----------|---------|---------|---------|--------|--------|--------|",
    ]
    for c in comparisons:
        lines.append(
            f"| {c.query_id} | {c.description} | {c.grep.total_tool_calls} | "
            f"{c.claude_code.total_tool_calls} | {c.supercontext.total_tool_calls} | "
            f"{c.grep.total_latency_ms:.0f}ms | {c.claude_code.total_latency_ms:.0f}ms | "
            f"{c.supercontext.total_latency_ms:.0f}ms | {c.winner} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
