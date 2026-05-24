"""
Evaluation: SuperContext KG vs grep baseline on github/CodeSearchNet.

Runs a battery of code-understanding queries against both:
  1. SuperContext KG (structural, AST-parsed knowledge graph)
  2. grep baseline (text search with ripgrep)

Produces structured JSON results in evals/codesearchnet/results/.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "codesearchnet"
RESULTS_DIR = EVAL_DIR / "results"
SNAPSHOT_DIR = REPO_ROOT / "data" / "kg_runs" / "codesearchnet"
CSN_REPO = Path(os.environ.get("CSN_REPO", str(REPO_ROOT.parent / "CodeSearchNet")))
ANNOTATIONS_CSV = CSN_REPO / "annotationStore.csv"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class EvalQuery:
    id: str
    category: str
    query_text: str
    description: str
    expected_answer_type: str

@dataclass
class EvalResult:
    query_id: str
    approach: str  # "supercontext" or "grep"
    query_text: str
    raw_result: Any
    result_count: int
    has_structural_info: bool
    has_evidence: bool
    has_qualified_names: bool
    has_transitive_deps: bool
    precision_notes: str
    latency_ms: float

@dataclass
class ComparisonRow:
    query_id: str
    category: str
    query_text: str
    sc_result_count: int
    grep_result_count: int
    sc_has_structure: bool
    grep_has_structure: bool
    sc_has_evidence: bool
    grep_has_evidence: bool
    sc_has_qualified_names: bool
    sc_has_transitive: bool
    sc_latency_ms: float
    grep_latency_ms: float
    winner: str
    reason: str


# ---------------------------------------------------------------------------
# Query battery: structural code understanding queries
# ---------------------------------------------------------------------------

EVAL_QUERIES: list[EvalQuery] = [
    # --- Dependency queries ---
    EvalQuery("DEP-01", "dependency", "modules-importing tensorflow", "Which modules import tensorflow?", "module_list"),
    EvalQuery("DEP-02", "dependency", "modules-importing wandb", "Which modules import wandb?", "module_list"),
    EvalQuery("DEP-03", "dependency", "modules-importing numpy", "Which modules import numpy?", "module_list"),
    EvalQuery("DEP-04", "dependency", "modules-importing docopt", "Which modules import docopt?", "module_list"),
    EvalQuery("DEP-05", "dependency", "top-dependencies", "What are the top external dependencies?", "ranked_list"),
    EvalQuery("DEP-06", "dependency", "top-internal-dependencies", "What are the top internal module dependencies?", "ranked_list"),

    # --- Call graph queries ---
    EvalQuery("CALL-01", "call_graph", "find-callers get_shape_list", "Who calls get_shape_list?", "caller_list"),
    EvalQuery("CALL-02", "call_graph", "find-callers create_initializer", "Who calls create_initializer?", "caller_list"),
    EvalQuery("CALL-03", "call_graph", "find-callers dropout", "Who calls dropout?", "caller_list"),
    EvalQuery("CALL-04", "call_graph", "find-callers train_log", "Who calls train_log?", "caller_list"),
    EvalQuery("CALL-05", "call_graph", "find-callees Model.train", "What does Model.train call?", "callee_list"),
    EvalQuery("CALL-06", "call_graph", "find-callees Model.make_model", "What does Model.make_model call?", "callee_list"),
    EvalQuery("CALL-07", "call_graph", "top-fan-in-symbols", "Which symbols have the most callers?", "ranked_list"),

    # --- Symbol queries ---
    EvalQuery("SYM-01", "symbol", "symbols-in-file src/models/model.py", "What symbols are defined in model.py?", "symbol_list"),
    EvalQuery("SYM-02", "symbol", "symbols-in-file src/encoders/seq_encoder.py", "What symbols are defined in seq_encoder.py?", "symbol_list"),
    EvalQuery("SYM-03", "symbol", "lookup-symbol Model", "Find the Model class definition", "symbol_detail"),
    EvalQuery("SYM-04", "symbol", "lookup-symbol SeqEncoder", "Find the SeqEncoder class definition", "symbol_detail"),
    EvalQuery("SYM-05", "symbol", "lookup-symbol NeuralBoWModel", "Find the NeuralBoWModel class", "symbol_detail"),

    # --- Blast radius queries ---
    EvalQuery("BLAST-01", "blast_radius", "blast-radius get_shape_list --depth 2", "What breaks if get_shape_list changes?", "graph_closure"),
    EvalQuery("BLAST-02", "blast_radius", "blast-radius Model.train --depth 2", "What breaks if Model.train changes?", "graph_closure"),
    EvalQuery("BLAST-03", "blast_radius", "blast-radius SeqEncoder --depth 2 --include-all", "What breaks if SeqEncoder changes?", "graph_closure"),

    # --- Structural queries ---
    EvalQuery("STRUCT-01", "structural", "summary", "Give me a codebase summary", "summary"),
    EvalQuery("STRUCT-02", "structural", "who-imports src.models.model", "Who imports the model module?", "importer_list"),
    EvalQuery("STRUCT-03", "structural", "who-imports src.encoders.seq_encoder", "Who imports seq_encoder?", "importer_list"),
    EvalQuery("STRUCT-04", "structural", "dependency-path Model.train get_shape_list", "Is there a dependency path from Model.train to get_shape_list?", "path"),
]


# ---------------------------------------------------------------------------
# SuperContext runner
# ---------------------------------------------------------------------------

def run_supercontext_query(query: EvalQuery) -> EvalResult:
    parts = query.query_text.split()
    cmd = ["python", "-m", "source.scripts.query_kg", "--snapshot", str(SNAPSHOT_DIR)]
    cmd.extend(parts)

    t0 = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
    latency = (time.monotonic() - t0) * 1000

    if r.returncode != 0:
        return EvalResult(
            query_id=query.id, approach="supercontext", query_text=query.query_text,
            raw_result={"error": r.stderr.strip()}, result_count=0,
            has_structural_info=False, has_evidence=False, has_qualified_names=False,
            has_transitive_deps=False, precision_notes=f"Error: {r.stderr[:200]}", latency_ms=latency,
        )

    data = json.loads(r.stdout)
    count = _count_results(data)
    has_evidence = _has_evidence(data)
    has_qnames = _has_qualified_names(data)
    has_transitive = query.category == "blast_radius" and len(data.get("edges", [])) > 0
    has_struct = count > 0

    return EvalResult(
        query_id=query.id, approach="supercontext", query_text=query.query_text,
        raw_result=data, result_count=count,
        has_structural_info=has_struct, has_evidence=has_evidence,
        has_qualified_names=has_qnames, has_transitive_deps=has_transitive,
        precision_notes=_precision_notes_sc(query, data, count),
        latency_ms=round(latency, 1),
    )


def _count_results(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("result_count", "caller_count", "callee_count"):
            if key in data:
                return data[key]
        if "results" in data and isinstance(data["results"], list):
            return len(data["results"])
        if "symbols" in data and isinstance(data["symbols"], list):
            return len(data["symbols"])
        if "entity_kinds" in data:
            return sum(data["entity_kinds"].values())
        if "edges" in data:
            return len(data["edges"])
        if "paths" in data:
            return len(data["paths"])
        if "groups" in data and isinstance(data["groups"], list):
            return sum(g.get("count", len(g.get("importers", []))) for g in data["groups"])
    return 0


def _has_evidence(data: Any) -> bool:
    raw = json.dumps(data)
    return '"evidence_id"' in raw or '"bytes_ref"' in raw or '"evidence"' in raw


def _has_qualified_names(data: Any) -> bool:
    raw = json.dumps(data)
    return '"qualified_name"' in raw or '"qualname"' in raw or '"display_name"' in raw


def _precision_notes_sc(query: EvalQuery, data: Any, count: int) -> str:
    if count == 0:
        status = data.get("status", "unknown") if isinstance(data, dict) else "empty"
        return f"No results (status={status})"
    notes = f"{count} results with AST-parsed structural data"
    if _has_evidence(data):
        notes += ", commit-pinned evidence"
    if _has_qualified_names(data):
        notes += ", qualified names"
    return notes


# ---------------------------------------------------------------------------
# Grep baseline runner
# ---------------------------------------------------------------------------

def run_grep_query(query: EvalQuery) -> EvalResult:
    t0 = time.monotonic()
    search_term, files, has_struct, notes = _grep_for_query(query)
    latency = (time.monotonic() - t0) * 1000

    return EvalResult(
        query_id=query.id, approach="grep", query_text=query.query_text,
        raw_result={"search_term": search_term, "matching_files": files},
        result_count=len(files),
        has_structural_info=has_struct,
        has_evidence=False,
        has_qualified_names=False,
        has_transitive_deps=False,
        precision_notes=notes,
        latency_ms=round(latency, 1),
    )


def _grep_for_query(query: EvalQuery) -> tuple[str, list[str], bool, str]:
    py_files_cmd = ["find", str(CSN_REPO), "-name", "*.py",
                    "-not", "-path", "*/resources/*", "-not", "-path", "*/notebooks/*"]

    if query.category == "dependency":
        if "modules-importing" in query.query_text:
            pkg = query.query_text.split()[-1]
            search = f"import {pkg}|from {pkg}"
            files = _grep_files(py_files_cmd, search)
            return search, files, False, f"Text match for import lines — no alias/category metadata"
        if "top-dependencies" in query.query_text:
            search = "^import |^from "
            lines = _grep_lines(py_files_cmd, search)
            pkgs = set()
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    pkgs.add(parts[1].split(".")[0])
            return search, sorted(pkgs), False, f"Regex for import lines — {len(pkgs)} unique roots, no ranking"
        if "top-internal" in query.query_text:
            search = "^from src\\.|^import src\\."
            files = _grep_files(py_files_cmd, search)
            return search, files, False, f"Regex for internal imports — flat file list, no ranking"

    elif query.category == "call_graph":
        if "find-callers" in query.query_text or "find-callees" in query.query_text:
            symbol = query.query_text.split()[-1]
            if "." in symbol:
                symbol = symbol.split(".")[-1]
            search = symbol
            files = _grep_files(py_files_cmd, search)
            lines = _grep_lines(py_files_cmd, search)
            return search, files, False, f"String match '{symbol}' — {len(lines)} lines in {len(files)} files, includes defs+comments+strings"
        if "top-fan-in" in query.query_text:
            return "N/A", [], False, "Not possible with grep — requires call graph analysis"

    elif query.category == "symbol":
        if "symbols-in-file" in query.query_text:
            filepath = query.query_text.split()[-1]
            full_path = CSN_REPO / filepath
            search = r"^\s*def |^\s*class "
            lines = _grep_lines_in_file(str(full_path), search)
            return search, lines, False, f"{len(lines)} def/class lines — no qualified names, no method ownership"
        if "lookup-symbol" in query.query_text:
            symbol = query.query_text.split()[-1]
            if "." in symbol:
                symbol = symbol.split(".")[-1]
            search = f"class {symbol}|def {symbol}"
            files = _grep_files(py_files_cmd, search)
            return search, files, False, f"String match for class/def — no module path, no line metadata"

    elif query.category == "blast_radius":
        symbol = query.query_text.split()[1]
        if "." in symbol:
            symbol = symbol.split(".")[-1]
        search = symbol
        files = _grep_files(py_files_cmd, search)
        return search, files, False, f"String match only — {len(files)} files mention '{symbol}', no transitive analysis"

    elif query.category == "structural":
        if "summary" in query.query_text:
            files = _find_py_files(py_files_cmd)
            return "find *.py", files, False, f"{len(files)} Python files found — no entity/relationship counts"
        if "who-imports" in query.query_text:
            module = query.query_text.split()[-1]
            module_parts = module.replace(".", "/")
            search = f"import {module}|from {module}|import {module_parts}"
            files = _grep_files(py_files_cmd, search)
            return search, files, False, f"String match for import — no grouping or prefix analysis"
        if "dependency-path" in query.query_text:
            return "N/A", [], False, "Not possible with grep — requires graph traversal"

    return "N/A", [], False, "Query type not mapped to grep"


def _grep_files(find_cmd: list[str], pattern: str) -> list[str]:
    r = subprocess.run(find_cmd, capture_output=True, text=True, timeout=10)
    if not r.stdout.strip():
        return []
    files = r.stdout.strip().split("\n")
    grep_r = subprocess.run(
        ["xargs", "grep", "-rl", "-E", pattern],
        input="\n".join(files), capture_output=True, text=True, timeout=10,
    )
    return [f for f in grep_r.stdout.strip().split("\n") if f]


def _grep_lines(find_cmd: list[str], pattern: str) -> list[str]:
    r = subprocess.run(find_cmd, capture_output=True, text=True, timeout=10)
    if not r.stdout.strip():
        return []
    files = r.stdout.strip().split("\n")
    grep_r = subprocess.run(
        ["xargs", "grep", "-rn", "-E", pattern],
        input="\n".join(files), capture_output=True, text=True, timeout=10,
    )
    return [l for l in grep_r.stdout.strip().split("\n") if l]


def _grep_lines_in_file(filepath: str, pattern: str) -> list[str]:
    r = subprocess.run(["grep", "-n", "-E", pattern, filepath], capture_output=True, text=True, timeout=10)
    return [l for l in r.stdout.strip().split("\n") if l]


def _find_py_files(find_cmd: list[str]) -> list[str]:
    r = subprocess.run(find_cmd, capture_output=True, text=True, timeout=10)
    return [f for f in r.stdout.strip().split("\n") if f]


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def compare(sc: EvalResult, grep: EvalResult, q: EvalQuery) -> ComparisonRow:
    if q.category == "blast_radius":
        winner = "supercontext" if sc.has_transitive_deps or sc.result_count > 0 else "tie"
        reason = "Transitive closure vs string match" if winner == "supercontext" else "Neither found results"
    elif q.category == "call_graph" and "top-fan-in" in q.query_text:
        winner = "supercontext"
        reason = "Call graph analysis not possible with grep"
    elif q.category == "structural" and "dependency-path" in q.query_text:
        winner = "supercontext"
        reason = "Graph traversal not possible with grep"
    elif sc.has_qualified_names and not grep.has_qualified_names:
        winner = "supercontext"
        reason = "Qualified names + evidence vs flat file matches"
    elif sc.result_count > 0 and grep.result_count == 0:
        winner = "supercontext"
        reason = "SuperContext found results, grep found none"
    elif sc.result_count == 0 and grep.result_count > 0:
        winner = "grep"
        reason = "Grep found results, SuperContext found none"
    elif sc.has_evidence:
        winner = "supercontext"
        reason = "Richer metadata (evidence, structure) for same coverage"
    else:
        winner = "tie"
        reason = "Similar coverage"

    return ComparisonRow(
        query_id=q.id, category=q.category, query_text=q.query_text,
        sc_result_count=sc.result_count, grep_result_count=grep.result_count,
        sc_has_structure=sc.has_structural_info, grep_has_structure=grep.has_structural_info,
        sc_has_evidence=sc.has_evidence, grep_has_evidence=grep.has_evidence,
        sc_has_qualified_names=sc.has_qualified_names,
        sc_has_transitive=sc.has_transitive_deps,
        sc_latency_ms=sc.latency_ms, grep_latency_ms=grep.latency_ms,
        winner=winner, reason=reason,
    )


# ---------------------------------------------------------------------------
# CodeSearchNet annotations analysis
# ---------------------------------------------------------------------------

def load_csn_annotations() -> dict[str, Any]:
    if not ANNOTATIONS_CSV.exists():
        return {"error": "annotationStore.csv not found"}

    with open(ANNOTATIONS_CSV) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    py_rows = [r for r in rows if r["Language"] == "Python"]
    queries = sorted(set(r["Query"] for r in py_rows))
    rels = [int(r["Relevance"]) for r in py_rows]

    return {
        "total_annotations": len(rows),
        "python_annotations": len(py_rows),
        "unique_python_queries": len(queries),
        "languages": sorted(set(r["Language"] for r in rows)),
        "relevance_distribution": {
            str(r): rels.count(r) for r in range(4)
        },
        "sample_queries": queries[:25],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[eval] Target repo: {CSN_REPO}")
    print(f"[eval] KG snapshot: {SNAPSHOT_DIR}")
    print(f"[eval] Running {len(EVAL_QUERIES)} queries...")
    print()

    sc_results: list[EvalResult] = []
    grep_results: list[EvalResult] = []
    comparisons: list[ComparisonRow] = []

    for i, q in enumerate(EVAL_QUERIES, 1):
        print(f"  [{i:2d}/{len(EVAL_QUERIES)}] {q.id}: {q.description}")

        sc = run_supercontext_query(q)
        sc_results.append(sc)

        grep = run_grep_query(q)
        grep_results.append(grep)

        comp = compare(sc, grep, q)
        comparisons.append(comp)

        mark = {"supercontext": "SC", "grep": "GR", "tie": "=="}[comp.winner]
        print(f"         SC: {sc.result_count:3d} results ({sc.latency_ms:.0f}ms) | "
              f"grep: {grep.result_count:3d} results ({grep.latency_ms:.0f}ms) | "
              f"Winner: {mark}")

    # --- Compute summary ---
    sc_wins = sum(1 for c in comparisons if c.winner == "supercontext")
    grep_wins = sum(1 for c in comparisons if c.winner == "grep")
    ties = sum(1 for c in comparisons if c.winner == "tie")
    sc_avg_latency = sum(r.latency_ms for r in sc_results) / len(sc_results)
    grep_avg_latency = sum(r.latency_ms for r in grep_results) / len(grep_results)

    by_category: dict[str, dict[str, int]] = {}
    for c in comparisons:
        cat = by_category.setdefault(c.category, {"supercontext": 0, "grep": 0, "tie": 0})
        cat[c.winner] += 1

    # --- CSN dataset analysis ---
    csn_annotations = load_csn_annotations()

    # --- Build final report ---
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_repo": str(CSN_REPO),
        "kg_snapshot": str(SNAPSHOT_DIR),
        "query_count": len(EVAL_QUERIES),
        "summary": {
            "supercontext_wins": sc_wins,
            "grep_wins": grep_wins,
            "ties": ties,
            "supercontext_win_rate": round(sc_wins / len(comparisons) * 100, 1),
            "avg_latency_ms": {
                "supercontext": round(sc_avg_latency, 1),
                "grep": round(grep_avg_latency, 1),
            },
        },
        "by_category": by_category,
        "comparisons": [asdict(c) for c in comparisons],
        "supercontext_results": [
            {k: v for k, v in asdict(r).items() if k != "raw_result"}
            for r in sc_results
        ],
        "grep_results": [
            {k: v for k, v in asdict(r).items() if k != "raw_result"}
            for r in grep_results
        ],
        "codesearchnet_dataset": csn_annotations,
    }

    # --- Write outputs ---
    report_path = RESULTS_DIR / "eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[eval] Report written to {report_path}")

    # Full raw results (with raw_result payloads)
    raw_path = RESULTS_DIR / "raw_results.json"
    with open(raw_path, "w") as f:
        json.dump({
            "supercontext": [asdict(r) for r in sc_results],
            "grep": [asdict(r) for r in grep_results],
        }, f, indent=2, default=str)
    print(f"[eval] Raw results written to {raw_path}")

    # Markdown summary
    md = _render_markdown(report, comparisons)
    md_path = RESULTS_DIR / "eval_report.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"[eval] Markdown report written to {md_path}")

    # Summary to stdout
    print(f"\n{'='*60}")
    print(f"RESULTS: SuperContext {sc_wins} | grep {grep_wins} | tie {ties}")
    print(f"Win rate: SuperContext {report['summary']['supercontext_win_rate']}%")
    print(f"Avg latency: SC {sc_avg_latency:.0f}ms | grep {grep_avg_latency:.0f}ms")
    print(f"{'='*60}")


def _render_markdown(report: dict, comparisons: list[ComparisonRow]) -> str:
    s = report["summary"]
    lines = [
        "# SuperContext vs grep Evaluation Report",
        f"",
        f"**Generated:** {report['generated_at']}",
        f"**Target:** github/CodeSearchNet ({report['query_count']} queries)",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| SuperContext wins | {s['supercontext_wins']} |",
        f"| grep wins | {s['grep_wins']} |",
        f"| Ties | {s['ties']} |",
        f"| SuperContext win rate | {s['supercontext_win_rate']}% |",
        f"| Avg latency (SC) | {s['avg_latency_ms']['supercontext']}ms |",
        f"| Avg latency (grep) | {s['avg_latency_ms']['grep']}ms |",
        f"",
        f"## Results by Category",
        f"",
        f"| Category | SC wins | grep wins | Ties |",
        f"|----------|---------|-----------|------|",
    ]
    for cat, counts in report["by_category"].items():
        lines.append(f"| {cat} | {counts['supercontext']} | {counts['grep']} | {counts['tie']} |")

    lines.extend([
        f"",
        f"## Per-Query Results",
        f"",
        f"| ID | Query | SC results | grep results | Winner | Reason |",
        f"|----|-------|-----------|-------------|--------|--------|",
    ])
    for c in comparisons:
        lines.append(f"| {c.query_id} | {c.query_text} | {c.sc_result_count} | {c.grep_result_count} | {c.winner} | {c.reason} |")

    if "codesearchnet_dataset" in report and "error" not in report["codesearchnet_dataset"]:
        ds = report["codesearchnet_dataset"]
        lines.extend([
            f"",
            f"## CodeSearchNet Dataset",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total annotations | {ds['total_annotations']} |",
            f"| Python annotations | {ds['python_annotations']} |",
            f"| Unique Python queries | {ds['unique_python_queries']} |",
            f"| Languages | {', '.join(ds['languages'])} |",
        ])

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
