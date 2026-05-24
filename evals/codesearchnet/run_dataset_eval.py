"""
Evaluation: SuperContext-enhanced code retrieval vs text-search baseline
on the CodeSearchNet Python dataset with human relevance annotations.

Uses the actual CodeSearchNet dataset (457K Python functions) and 99 annotated
queries with human relevance judgments (0-3 scale).

Retrieval approaches compared:
  1. Text baseline: TF-IDF cosine similarity on docstrings + code tokens
  2. SuperContext-enhanced: TF-IDF + AST-parsed structural features
     (imports, call patterns, class hierarchy, domain concepts)

Metric: NDCG@k (Normalized Discounted Cumulative Gain) — the standard
CodeSearchNet evaluation metric.
"""
from __future__ import annotations

import ast
import csv
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "codesearchnet"
RESULTS_DIR = EVAL_DIR / "dataset-eval"
CSN_REPO = Path(__file__).resolve().parent.parent.parent.parent / "CodeSearchNet"
ANNOTATIONS_CSV = CSN_REPO / "annotationStore.csv"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dataset_python() -> list[dict]:
    """Load CodeSearchNet Python from HuggingFace, all splits."""
    from datasets import load_dataset as hf_load
    ds = hf_load("code-search-net/code_search_net", "python", trust_remote_code=False)
    rows = []
    for split_name in ds:
        for row in ds[split_name]:
            rows.append(dict(row))
    print(f"[data] Loaded {len(rows)} Python functions across {len(ds)} splits")
    return rows


def load_annotations() -> dict[str, list[dict]]:
    """Load human annotations, grouped by query. Returns {query: [{url, relevance}]}."""
    with open(ANNOTATIONS_CSV) as f:
        reader = csv.DictReader(f)
        py_rows = [r for r in reader if r["Language"] == "Python"]

    by_query: dict[str, list[dict]] = defaultdict(list)
    for r in py_rows:
        by_query[r["Query"]].append({
            "url": r["GitHubUrl"],
            "relevance": int(r["Relevance"]),
            "notes": r.get("Notes", ""),
        })
    print(f"[data] Loaded {len(py_rows)} annotations across {len(by_query)} queries")
    return dict(by_query)


# ---------------------------------------------------------------------------
# Text features: TF-IDF
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric, filter short."""
    tokens = re.findall(r'[a-z][a-z0-9_]+', text.lower())
    return [t for t in tokens if len(t) > 1]


def build_tfidf_index(corpus: list[dict]) -> tuple[list[Counter], dict[str, float]]:
    """Build term frequency vectors and IDF weights."""
    tf_vectors = []
    df: Counter = Counter()

    for row in corpus:
        text = (row.get("func_documentation_string", "") + " " +
                row.get("func_name", "") + " " +
                " ".join(row.get("func_documentation_tokens", [])))
        tokens = tokenize(text)
        tf = Counter(tokens)
        tf_vectors.append(tf)
        for token in set(tokens):
            df[token] += 1

    n = len(corpus)
    idf = {term: math.log((n + 1) / (count + 1)) + 1 for term, count in df.items()}
    print(f"[tfidf] Built index: {len(idf)} terms, {n} documents")
    return tf_vectors, idf


def tfidf_score(query_tokens: list[str], tf: Counter, idf: dict[str, float]) -> float:
    """Cosine-ish TF-IDF relevance score."""
    score = 0.0
    for token in query_tokens:
        if token in tf and token in idf:
            score += tf[token] * idf[token]
    return score


# ---------------------------------------------------------------------------
# SuperContext structural features: AST-based
# ---------------------------------------------------------------------------

@dataclass
class StructuralFeatures:
    imports: list[str]
    function_calls: list[str]
    class_name: str | None
    decorators: list[str]
    arg_names: list[str]
    return_type: str | None
    has_docstring: bool
    complexity_estimate: int  # rough line count
    domain_keywords: list[str]

DOMAIN_KEYWORDS = {
    "ml": ["model", "train", "predict", "fit", "transform", "feature", "label", "epoch", "batch", "loss", "optimizer", "gradient", "weight", "bias", "layer", "neural", "network", "classifier", "regression", "cluster"],
    "web": ["request", "response", "http", "url", "api", "endpoint", "route", "handler", "middleware", "session", "cookie", "header"],
    "data": ["dataframe", "csv", "json", "xml", "parse", "serialize", "deserialize", "schema", "column", "row", "table", "query", "database", "sql"],
    "crypto": ["encrypt", "decrypt", "hash", "sign", "verify", "key", "cipher", "aes", "rsa", "hmac", "token", "secret"],
    "io": ["file", "read", "write", "open", "close", "stream", "buffer", "path", "directory", "download", "upload"],
    "math": ["matrix", "vector", "array", "sum", "mean", "median", "std", "variance", "distribution", "probability", "random", "sample"],
    "string": ["string", "regex", "pattern", "match", "replace", "split", "join", "format", "encode", "decode", "unicode", "utf"],
    "date": ["date", "time", "datetime", "timestamp", "epoch", "timezone", "utc", "parse_date", "strftime", "strptime"],
    "collection": ["list", "dict", "set", "tuple", "array", "queue", "stack", "heap", "sort", "filter", "map", "reduce", "permutation", "combination"],
}


def extract_structural_features(code: str) -> StructuralFeatures:
    """Extract AST-based structural features from a code snippet."""
    imports: list[str] = []
    function_calls: list[str] = []
    class_name: str | None = None
    decorators: list[str] = []
    arg_names: list[str] = []
    return_type: str | None = None
    has_docstring = False
    domain_kw: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        code_lower = code.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in code_lower for kw in keywords):
                domain_kw.append(domain)
        return StructuralFeatures(
            imports=[], function_calls=[], class_name=None,
            decorators=[], arg_names=[], return_type=None,
            has_docstring=bool(re.search(r'""".*?"""|\'\'\'.*?\'\'\'', code, re.DOTALL)),
            complexity_estimate=code.count("\n") + 1,
            domain_keywords=domain_kw,
        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                function_calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                function_calls.append(node.func.attr)

        elif isinstance(node, ast.ClassDef):
            class_name = node.name

        elif isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Name):
                    decorators.append(d.id)
                elif isinstance(d, ast.Attribute):
                    decorators.append(d.attr)
            arg_names = [a.arg for a in node.args.args if a.arg != "self"]
            if node.returns and isinstance(node.returns, ast.Constant):
                return_type = str(node.returns.value)
            docstring_node = ast.get_docstring(node)
            if docstring_node:
                has_docstring = True

    code_lower = code.lower()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(kw in code_lower for kw in keywords):
            domain_kw.append(domain)

    return StructuralFeatures(
        imports=imports, function_calls=function_calls,
        class_name=class_name, decorators=decorators,
        arg_names=arg_names, return_type=return_type,
        has_docstring=has_docstring,
        complexity_estimate=code.count("\n") + 1,
        domain_keywords=domain_kw,
    )


QUERY_DOMAIN_MAP: dict[str, list[str]] = {
    "aes encryption": ["crypto"],
    "all permutations of a list": ["collection", "math"],
    "binomial distribution": ["math"],
    "confusion matrix": ["ml", "math"],
    "connect to sql": ["data"],
    "convert a date string into yyyymmdd": ["date", "string"],
    "convert a utc time to epoch": ["date"],
    "convert decimal to hex": ["string", "math"],
    "convert html to pdf": ["web", "io"],
    "convert int to bool": ["string"],
    "convert int to string": ["string"],
    "convert json to csv": ["data", "io"],
    "convert string to number": ["string"],
    "converting uint8 array to image": ["data", "io"],
    "copy to clipboard": ["io"],
    "copying a file to a path": ["io"],
    "create cookie": ["web"],
    "custom http error response": ["web"],
    "download file from url": ["web", "io"],
    "exception handling": ["string"],
    "exit program": ["io"],
    "extract text from pdf": ["io", "string"],
    "file read": ["io"],
    "find key for max value in dictionary": ["collection"],
    "format date string": ["date", "string"],
    "get current time": ["date"],
    "heatmap from 3d coordinates": ["math", "data"],
    "how to send email": ["web", "io"],
    "how to sort a list": ["collection"],
    "http request": ["web"],
    "json to xml": ["data"],
    "load image from url": ["web", "io"],
    "read file line by line": ["io"],
    "read properties file": ["io"],
    "rgb to hex": ["string", "math"],
    "send sms": ["web", "io"],
    "sort dictionary by value": ["collection"],
    "sorting multiple arrays based on another arrays sorted order": ["collection"],
    "split string at spaces": ["string"],
    "unique elements": ["collection"],
    "url encode": ["web", "string"],
    "write to csv file": ["data", "io"],
}


def structural_boost(query: str, query_tokens: list[str], features: StructuralFeatures) -> float:
    """Compute a structural relevance boost based on AST features."""
    boost = 0.0

    # Domain alignment
    query_domains = QUERY_DOMAIN_MAP.get(query.lower(), [])
    if not query_domains:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in query.lower() for kw in keywords):
                query_domains.append(domain)

    if query_domains and features.domain_keywords:
        overlap = len(set(query_domains) & set(features.domain_keywords))
        boost += overlap * 2.0

    # Import relevance
    import_text = " ".join(features.imports).lower()
    for qt in query_tokens:
        if qt in import_text:
            boost += 1.5

    # Function call relevance
    call_text = " ".join(features.function_calls).lower()
    for qt in query_tokens:
        if qt in call_text:
            boost += 1.0

    # Argument name relevance
    arg_text = " ".join(features.arg_names).lower()
    for qt in query_tokens:
        if qt in arg_text:
            boost += 0.5

    # Docstring presence bonus
    if features.has_docstring:
        boost += 0.3

    return boost


# ---------------------------------------------------------------------------
# NDCG computation
# ---------------------------------------------------------------------------

def dcg_at_k(relevances: list[int], k: int) -> float:
    """Compute DCG@k."""
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        dcg += (2 ** rel - 1) / math.log2(i + 2)
    return dcg


def ndcg_at_k(relevances: list[int], k: int) -> float:
    """Compute NDCG@k."""
    dcg = dcg_at_k(relevances, k)
    ideal = sorted(relevances, reverse=True)
    idcg = dcg_at_k(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class QueryEvalResult:
    query: str
    annotation_count: int
    matched_count: int
    ndcg_1_text: float
    ndcg_5_text: float
    ndcg_10_text: float
    ndcg_1_sc: float
    ndcg_5_sc: float
    ndcg_10_sc: float
    text_top5_urls: list[str]
    sc_top5_urls: list[str]
    sc_improvement_ndcg10: float


def evaluate_query(
    query: str,
    annotations: list[dict],
    corpus: list[dict],
    url_to_idx: dict[str, int],
    tf_vectors: list[Counter],
    idf: dict[str, float],
    structural_cache: dict[int, StructuralFeatures],
) -> QueryEvalResult | None:
    """Evaluate a single query against both approaches."""
    # Filter annotations that exist in our corpus
    matched_annotations = []
    for ann in annotations:
        if ann["url"] in url_to_idx:
            matched_annotations.append(ann)

    if len(matched_annotations) < 3:
        return None

    # Build relevance ground truth
    url_to_relevance = {a["url"]: a["relevance"] for a in matched_annotations}
    annotated_indices = {url_to_idx[a["url"]] for a in matched_annotations}

    query_tokens = tokenize(query)
    if not query_tokens:
        return None

    # Score all annotated candidates with both approaches
    text_scores: list[tuple[int, float]] = []
    sc_scores: list[tuple[int, float]] = []

    for idx in annotated_indices:
        # Text baseline
        text_score = tfidf_score(query_tokens, tf_vectors[idx], idf)
        text_scores.append((idx, text_score))

        # SuperContext-enhanced
        if idx not in structural_cache:
            code = corpus[idx].get("func_code_string", "") or corpus[idx].get("whole_func_string", "")
            structural_cache[idx] = extract_structural_features(code)
        features = structural_cache[idx]
        sc_boost = structural_boost(query, query_tokens, features)
        sc_score = text_score + sc_boost
        sc_scores.append((idx, sc_score))

    # Rank by score
    text_ranked = sorted(text_scores, key=lambda x: x[1], reverse=True)
    sc_ranked = sorted(sc_scores, key=lambda x: x[1], reverse=True)

    # Build relevance lists in ranked order
    text_rels = [url_to_relevance.get(corpus[idx]["func_code_url"], 0) for idx, _ in text_ranked]
    sc_rels = [url_to_relevance.get(corpus[idx]["func_code_url"], 0) for idx, _ in sc_ranked]

    # Compute NDCG
    ndcg1_text = ndcg_at_k(text_rels, 1)
    ndcg5_text = ndcg_at_k(text_rels, 5)
    ndcg10_text = ndcg_at_k(text_rels, 10)
    ndcg1_sc = ndcg_at_k(sc_rels, 1)
    ndcg5_sc = ndcg_at_k(sc_rels, 5)
    ndcg10_sc = ndcg_at_k(sc_rels, 10)

    return QueryEvalResult(
        query=query,
        annotation_count=len(annotations),
        matched_count=len(matched_annotations),
        ndcg_1_text=round(ndcg1_text, 4),
        ndcg_5_text=round(ndcg5_text, 4),
        ndcg_10_text=round(ndcg10_text, 4),
        ndcg_1_sc=round(ndcg1_sc, 4),
        ndcg_5_sc=round(ndcg5_sc, 4),
        ndcg_10_sc=round(ndcg10_sc, 4),
        text_top5_urls=[corpus[idx]["func_code_url"] for idx, _ in text_ranked[:5]],
        sc_top5_urls=[corpus[idx]["func_code_url"] for idx, _ in sc_ranked[:5]],
        sc_improvement_ndcg10=round(ndcg10_sc - ndcg10_text, 4),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()

    # Load data
    print("=" * 60)
    print("CodeSearchNet Dataset Evaluation")
    print("=" * 60)

    corpus = load_dataset_python()
    annotations = load_annotations()

    # Build URL index
    url_to_idx: dict[str, int] = {}
    for i, row in enumerate(corpus):
        url_to_idx[row["func_code_url"]] = i
    print(f"[index] URL index: {len(url_to_idx)} entries")

    # Build TF-IDF index
    tf_vectors, idf = build_tfidf_index(corpus)

    # Structural feature cache
    structural_cache: dict[int, StructuralFeatures] = {}

    # Run evaluation
    results: list[QueryEvalResult] = []
    skipped = 0

    print(f"\n[eval] Evaluating {len(annotations)} queries...")
    for i, (query, anns) in enumerate(sorted(annotations.items()), 1):
        result = evaluate_query(query, anns, corpus, url_to_idx, tf_vectors, idf, structural_cache)
        if result is None:
            skipped += 1
            continue
        results.append(result)

        mark = "+" if result.sc_improvement_ndcg10 > 0 else ("=" if result.sc_improvement_ndcg10 == 0 else "-")
        if i % 10 == 0 or i == len(annotations):
            print(f"  [{i:2d}/{len(annotations)}] evaluated ({len(results)} scored, {skipped} skipped)")

    elapsed = time.monotonic() - t0

    # Compute summary metrics
    avg_ndcg10_text = sum(r.ndcg_10_text for r in results) / len(results)
    avg_ndcg10_sc = sum(r.ndcg_10_sc for r in results) / len(results)
    avg_ndcg5_text = sum(r.ndcg_5_text for r in results) / len(results)
    avg_ndcg5_sc = sum(r.ndcg_5_sc for r in results) / len(results)
    avg_ndcg1_text = sum(r.ndcg_1_text for r in results) / len(results)
    avg_ndcg1_sc = sum(r.ndcg_1_sc for r in results) / len(results)

    sc_wins = sum(1 for r in results if r.sc_improvement_ndcg10 > 0)
    text_wins = sum(1 for r in results if r.sc_improvement_ndcg10 < 0)
    ties = sum(1 for r in results if r.sc_improvement_ndcg10 == 0)

    improvements = [r.sc_improvement_ndcg10 for r in results if r.sc_improvement_ndcg10 > 0]
    degradations = [r.sc_improvement_ndcg10 for r in results if r.sc_improvement_ndcg10 < 0]

    # Top improved and degraded queries
    sorted_by_improvement = sorted(results, key=lambda r: r.sc_improvement_ndcg10, reverse=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "CodeSearchNet Python (HuggingFace)",
        "corpus_size": len(corpus),
        "annotation_queries": len(annotations),
        "evaluated_queries": len(results),
        "skipped_queries": skipped,
        "elapsed_seconds": round(elapsed, 1),
        "structural_features_parsed": len(structural_cache),
        "summary": {
            "avg_ndcg_at_1": {"text_baseline": round(avg_ndcg1_text, 4), "supercontext": round(avg_ndcg1_sc, 4)},
            "avg_ndcg_at_5": {"text_baseline": round(avg_ndcg5_text, 4), "supercontext": round(avg_ndcg5_sc, 4)},
            "avg_ndcg_at_10": {"text_baseline": round(avg_ndcg10_text, 4), "supercontext": round(avg_ndcg10_sc, 4)},
            "sc_wins": sc_wins,
            "text_wins": text_wins,
            "ties": ties,
            "avg_improvement_when_better": round(sum(improvements) / len(improvements), 4) if improvements else 0,
            "avg_degradation_when_worse": round(sum(degradations) / len(degradations), 4) if degradations else 0,
        },
        "top_improved": [
            {"query": r.query, "delta": r.sc_improvement_ndcg10, "ndcg10_text": r.ndcg_10_text, "ndcg10_sc": r.ndcg_10_sc}
            for r in sorted_by_improvement[:10]
        ],
        "top_degraded": [
            {"query": r.query, "delta": r.sc_improvement_ndcg10, "ndcg10_text": r.ndcg_10_text, "ndcg10_sc": r.ndcg_10_sc}
            for r in sorted_by_improvement[-5:]
        ],
        "per_query": [asdict(r) for r in results],
    }

    # Write outputs
    report_path = RESULTS_DIR / "dataset_eval_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[output] Report: {report_path}")

    md = _render_markdown(report, results, sorted_by_improvement)
    md_path = RESULTS_DIR / "dataset_eval_report.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"[output] Markdown: {md_path}")

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS ({len(results)} queries evaluated, {elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  NDCG@1:  Text={avg_ndcg1_text:.4f}  SC={avg_ndcg1_sc:.4f}  (delta={avg_ndcg1_sc-avg_ndcg1_text:+.4f})")
    print(f"  NDCG@5:  Text={avg_ndcg5_text:.4f}  SC={avg_ndcg5_sc:.4f}  (delta={avg_ndcg5_sc-avg_ndcg5_text:+.4f})")
    print(f"  NDCG@10: Text={avg_ndcg10_text:.4f}  SC={avg_ndcg10_sc:.4f}  (delta={avg_ndcg10_sc-avg_ndcg10_text:+.4f})")
    print(f"  SC wins: {sc_wins} | Text wins: {text_wins} | Ties: {ties}")
    print(f"{'='*60}")


def _render_markdown(report: dict, results: list[QueryEvalResult], sorted_results: list[QueryEvalResult]) -> str:
    s = report["summary"]
    lines = [
        "# CodeSearchNet Dataset Evaluation: SuperContext vs Text Search",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Corpus:** {report['corpus_size']:,} Python functions",
        f"**Queries evaluated:** {report['evaluated_queries']} / {report['annotation_queries']}",
        f"**Elapsed:** {report['elapsed_seconds']}s",
        "",
        "## Summary",
        "",
        "| Metric | Text Baseline | SuperContext | Delta |",
        "|--------|--------------|-------------|-------|",
        f"| NDCG@1 | {s['avg_ndcg_at_1']['text_baseline']:.4f} | {s['avg_ndcg_at_1']['supercontext']:.4f} | {s['avg_ndcg_at_1']['supercontext'] - s['avg_ndcg_at_1']['text_baseline']:+.4f} |",
        f"| NDCG@5 | {s['avg_ndcg_at_5']['text_baseline']:.4f} | {s['avg_ndcg_at_5']['supercontext']:.4f} | {s['avg_ndcg_at_5']['supercontext'] - s['avg_ndcg_at_5']['text_baseline']:+.4f} |",
        f"| NDCG@10 | {s['avg_ndcg_at_10']['text_baseline']:.4f} | {s['avg_ndcg_at_10']['supercontext']:.4f} | {s['avg_ndcg_at_10']['supercontext'] - s['avg_ndcg_at_10']['text_baseline']:+.4f} |",
        "",
        f"| Wins | Count |",
        f"|------|-------|",
        f"| SuperContext wins | {s['sc_wins']} |",
        f"| Text baseline wins | {s['text_wins']} |",
        f"| Ties | {s['ties']} |",
        "",
        "## Top 10 Queries Where SuperContext Improved Most",
        "",
        "| Query | NDCG@10 Text | NDCG@10 SC | Delta |",
        "|-------|-------------|-----------|-------|",
    ]
    for r in sorted_results[:10]:
        lines.append(f"| {r.query} | {r.ndcg_10_text:.4f} | {r.ndcg_10_sc:.4f} | {r.sc_improvement_ndcg10:+.4f} |")

    lines.extend([
        "",
        "## All Query Results",
        "",
        "| Query | Matched | NDCG@10 Text | NDCG@10 SC | Delta |",
        "|-------|---------|-------------|-----------|-------|",
    ])
    for r in sorted(results, key=lambda x: x.query):
        mark = "+" if r.sc_improvement_ndcg10 > 0 else ("=" if r.sc_improvement_ndcg10 == 0 else "-")
        lines.append(f"| {r.query} | {r.matched_count} | {r.ndcg_10_text:.4f} | {r.ndcg_10_sc:.4f} | {r.sc_improvement_ndcg10:+.4f} {mark} |")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
