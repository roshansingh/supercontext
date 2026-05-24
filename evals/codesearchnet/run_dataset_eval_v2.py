"""
CodeSearchNet Dataset Eval v2: Full-corpus retrieval with NDCG.

Compares against published CodeSearchNet Challenge baselines (Python):
  - ElasticSearch:  NDCG_Within=0.406, NDCG_All=0.256
  - Neural BoW:     NDCG_Within=0.279, NDCG_All=0.223
  - 1D-CNN:         NDCG_Within=0.341, NDCG_All=0.166
  - biRNN:          NDCG_Within=0.169, NDCG_All=0.064

Key improvement over v1: retrieves from the FULL corpus (~457K functions)
then ranks, matching the actual CodeSearchNet evaluation methodology.

NDCG "Within" = computed only over annotated functions.
NDCG "All"    = computed over all functions in corpus (top-1000 window).
"""
from __future__ import annotations

import ast as python_ast
import csv
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "evals" / "codesearchnet"
RESULTS_DIR = EVAL_DIR / "dataset-eval"
CSN_REPO = REPO_ROOT.parent / "CodeSearchNet"
ANNOTATIONS_CSV = CSN_REPO / "annotationStore.csv"

PUBLISHED_BASELINES = {
    "ElasticSearch":    {"ndcg_within": 0.406, "ndcg_all": 0.256},
    "Neural BoW":       {"ndcg_within": 0.279, "ndcg_all": 0.223},
    "1D-CNN":           {"ndcg_within": 0.341, "ndcg_all": 0.166},
    "biRNN":            {"ndcg_within": 0.169, "ndcg_all": 0.064},
}

DOMAIN_KEYWORDS = {
    "ml": {"model", "train", "predict", "fit", "transform", "feature", "label",
           "epoch", "batch", "loss", "optimizer", "gradient", "weight", "layer",
           "neural", "network", "classifier", "regression"},
    "web": {"request", "response", "http", "url", "api", "endpoint", "route",
            "handler", "session", "cookie", "header"},
    "data": {"dataframe", "csv", "json", "xml", "parse", "serialize", "schema",
             "column", "row", "table", "query", "database", "sql"},
    "crypto": {"encrypt", "decrypt", "hash", "sign", "verify", "key", "cipher",
               "aes", "rsa", "hmac", "token", "secret"},
    "io": {"file", "read", "write", "open", "close", "stream", "buffer", "path",
           "directory", "download", "upload"},
    "math": {"matrix", "vector", "array", "sum", "mean", "median", "distribution",
             "probability", "random", "sample"},
    "string": {"string", "regex", "pattern", "match", "replace", "split", "join",
               "format", "encode", "decode"},
    "date": {"date", "time", "datetime", "timestamp", "epoch", "timezone", "utc"},
    "collection": {"list", "dict", "set", "sort", "filter", "map", "reduce",
                    "permutation", "combination", "queue", "stack"},
}

_TOKEN_RE = re.compile(r'[a-z][a-z0-9_]+')


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def load_dataset_python() -> list[dict]:
    from datasets import load_dataset as hf_load
    ds = hf_load("code-search-net/code_search_net", "python", trust_remote_code=False)
    rows = []
    for split_name in ds:
        for row in ds[split_name]:
            rows.append(dict(row))
    print(f"  Loaded {len(rows)} Python functions from all splits")
    return rows


def load_annotations() -> dict[str, list[dict]]:
    with open(ANNOTATIONS_CSV) as f:
        reader = csv.DictReader(f)
        py_rows = [r for r in reader if r["Language"] == "Python"]
    by_query: dict[str, list[dict]] = defaultdict(list)
    for r in py_rows:
        by_query[r["Query"]].append({"url": r["GitHubUrl"], "relevance": int(r["Relevance"])})
    print(f"  {len(py_rows)} annotations across {len(by_query)} queries")
    return dict(by_query)


# ---------------------------------------------------------------------------
# Phase 1: Pre-compute features ONCE for all 457K functions
# ---------------------------------------------------------------------------

@dataclass
class DocFeatures:
    tf: Counter
    domain_tags: set  # set of domain names present in code
    call_tokens: set  # function call names (lowered)
    import_tokens: set  # imported module names (lowered)


def precompute_features(corpus: list[dict]) -> tuple[list[DocFeatures], dict[str, float]]:
    """Build TF-IDF index and extract structural features in one pass."""
    features: list[DocFeatures] = []
    df: Counter = Counter()
    total = len(corpus)

    for i, row in enumerate(corpus):
        doc_text = " ".join(filter(None, [
            row.get("func_documentation_string", ""),
            row.get("func_name", ""),
        ]))
        doc_tokens = row.get("func_documentation_tokens")
        if doc_tokens:
            doc_text += " " + " ".join(doc_tokens)

        tf = Counter(tokenize(doc_text))
        for t in tf:
            df[t] += 1

        # Structural features from code
        code = row.get("func_code_string", "") or ""
        code_lower = code.lower()
        domain_tags: set[str] = set()
        for domain, kws in DOMAIN_KEYWORDS.items():
            if any(kw in code_lower for kw in kws):
                domain_tags.add(domain)

        call_tokens: set[str] = set()
        import_tokens: set[str] = set()
        try:
            tree = python_ast.parse(code)
            for node in python_ast.walk(tree):
                if isinstance(node, python_ast.Call):
                    if isinstance(node.func, python_ast.Name):
                        call_tokens.add(node.func.id.lower())
                    elif isinstance(node.func, python_ast.Attribute):
                        call_tokens.add(node.func.attr.lower())
                elif isinstance(node, python_ast.ImportFrom) and node.module:
                    import_tokens.add(node.module.split(".")[0].lower())
                elif isinstance(node, python_ast.Import):
                    for alias in node.names:
                        import_tokens.add(alias.name.split(".")[0].lower())
        except (SyntaxError, ValueError, RecursionError):
            pass

        features.append(DocFeatures(tf=tf, domain_tags=domain_tags,
                                     call_tokens=call_tokens, import_tokens=import_tokens))

        if (i + 1) % 50000 == 0:
            print(f"    [{i+1}/{total}] features extracted")

    n = len(corpus)
    idf = {term: math.log((n + 1) / (count + 1)) + 1 for term, count in df.items()}
    print(f"  IDF vocabulary: {len(idf)} terms")
    return features, idf


# ---------------------------------------------------------------------------
# Phase 2: Score functions per query
# ---------------------------------------------------------------------------

def tfidf_score(query_tokens: list[str], tf: Counter, idf: dict[str, float]) -> float:
    s = 0.0
    for t in query_tokens:
        if t in tf and t in idf:
            s += tf[t] * idf[t]
    return s


def structural_boost(query_tokens: set[str], query_domains: set[str],
                     feat: DocFeatures) -> float:
    boost = 0.0
    if query_domains & feat.domain_tags:
        boost += 1.5 * len(query_domains & feat.domain_tags)
    matched_calls = query_tokens & feat.call_tokens
    boost += 0.8 * len(matched_calls)
    matched_imports = query_tokens & feat.import_tokens
    boost += 0.5 * len(matched_imports)
    return boost


def query_domains(query_tokens: set[str]) -> set[str]:
    domains: set[str] = set()
    for domain, kws in DOMAIN_KEYWORDS.items():
        if query_tokens & kws:
            domains.add(domain)
    return domains


# ---------------------------------------------------------------------------
# NDCG
# ---------------------------------------------------------------------------

def dcg_at_k(rels: list[float], k: int) -> float:
    dcg = 0.0
    for i, r in enumerate(rels[:k]):
        dcg += (2 ** r - 1) / math.log2(i + 2)
    return dcg


def ndcg_at_k(rels: list[float], k: int) -> float:
    dcg = dcg_at_k(rels, k)
    ideal = sorted(rels, reverse=True)
    idcg = dcg_at_k(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query: str
    n_annotations: int
    n_matched: int
    ndcg_within_text: float
    ndcg_within_sc: float
    ndcg_all_text: float
    ndcg_all_sc: float


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("CodeSearchNet Dataset Eval v2 — Full Corpus Retrieval")
    print("=" * 70)
    t0 = time.monotonic()

    # Load data
    print("\n[1/5] Loading dataset...")
    corpus = load_dataset_python()
    annotations = load_annotations()

    url_to_idx: dict[str, int] = {}
    for i, row in enumerate(corpus):
        url_to_idx[row["func_code_url"]] = i
    print(f"  URL index: {len(url_to_idx)} entries")

    # Pre-compute all features
    print("\n[2/5] Pre-computing features (TF-IDF + structural)...")
    features, idf = precompute_features(corpus)

    # Evaluate
    print("\n[3/5] Scoring queries against full corpus...")
    results: list[QueryResult] = []
    skipped = 0
    n_queries = len(annotations)

    for qi, (query_text, anns) in enumerate(sorted(annotations.items()), 1):
        q_tokens_list = tokenize(query_text)
        if not q_tokens_list:
            skipped += 1
            continue

        q_tokens_set = set(q_tokens_list)
        q_domains = query_domains(q_tokens_set)

        url_rel = {a["url"]: a["relevance"] for a in anns}
        matched_urls = {u for u in url_rel if u in url_to_idx}
        if len(matched_urls) < 3:
            skipped += 1
            continue

        annotated_indices = {url_to_idx[u] for u in matched_urls}

        # Score all docs
        text_scores = []
        sc_scores = []
        for i in range(len(corpus)):
            feat = features[i]
            ts = tfidf_score(q_tokens_list, feat.tf, idf)
            sb = structural_boost(q_tokens_set, q_domains, feat)
            text_scores.append((i, ts))
            sc_scores.append((i, ts + sb))

        text_ranked = sorted(text_scores, key=lambda x: -x[1])
        sc_ranked = sorted(sc_scores, key=lambda x: -x[1])

        # NDCG Within: rank of annotated entries relative to each other
        text_within_rels = []
        sc_within_rels = []
        for idx, _ in text_ranked:
            if idx in annotated_indices:
                url = corpus[idx]["func_code_url"]
                text_within_rels.append(url_rel.get(url, 0))
        for idx, _ in sc_ranked:
            if idx in annotated_indices:
                url = corpus[idx]["func_code_url"]
                sc_within_rels.append(url_rel.get(url, 0))

        ndcg_w_text = ndcg_at_k(text_within_rels, len(text_within_rels))
        ndcg_w_sc = ndcg_at_k(sc_within_rels, len(sc_within_rels))

        # NDCG All: top-1000 window across full corpus
        text_all_rels = []
        sc_all_rels = []
        for idx, _ in text_ranked[:1000]:
            url = corpus[idx]["func_code_url"]
            text_all_rels.append(url_rel.get(url, 0))
        for idx, _ in sc_ranked[:1000]:
            url = corpus[idx]["func_code_url"]
            sc_all_rels.append(url_rel.get(url, 0))

        ndcg_a_text = ndcg_at_k(text_all_rels, 1000)
        ndcg_a_sc = ndcg_at_k(sc_all_rels, 1000)

        results.append(QueryResult(
            query=query_text, n_annotations=len(anns), n_matched=len(matched_urls),
            ndcg_within_text=round(ndcg_w_text, 4),
            ndcg_within_sc=round(ndcg_w_sc, 4),
            ndcg_all_text=round(ndcg_a_text, 4),
            ndcg_all_sc=round(ndcg_a_sc, 4),
        ))

        if qi % 10 == 0 or qi == n_queries:
            elapsed_q = time.monotonic() - t0
            print(f"  [{qi}/{n_queries}] {len(results)} evaluated | {elapsed_q:.0f}s elapsed")

    elapsed = time.monotonic() - t0

    # Aggregate
    avg = lambda field: round(sum(getattr(r, field) for r in results) / len(results), 4) if results else 0
    avg_nw_text = avg("ndcg_within_text")
    avg_nw_sc = avg("ndcg_within_sc")
    avg_na_text = avg("ndcg_all_text")
    avg_na_sc = avg("ndcg_all_sc")

    within_sc_wins = sum(1 for r in results if r.ndcg_within_sc > r.ndcg_within_text)
    within_text_wins = sum(1 for r in results if r.ndcg_within_text > r.ndcg_within_sc)
    within_ties = sum(1 for r in results if abs(r.ndcg_within_text - r.ndcg_within_sc) < 1e-9)

    all_sc_wins = sum(1 for r in results if r.ndcg_all_sc > r.ndcg_all_text)
    all_text_wins = sum(1 for r in results if r.ndcg_all_text > r.ndcg_all_sc)
    all_ties = sum(1 for r in results if abs(r.ndcg_all_text - r.ndcg_all_sc) < 1e-9)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v2_full_corpus",
        "corpus_size": len(corpus),
        "queries_evaluated": len(results),
        "queries_skipped": skipped,
        "elapsed_seconds": round(elapsed, 1),
        "our_results": {
            "ndcg_within": {"text_baseline_tfidf": avg_nw_text, "supercontext_enhanced": avg_nw_sc},
            "ndcg_all": {"text_baseline_tfidf": avg_na_text, "supercontext_enhanced": avg_na_sc},
            "within_wins": {"sc": within_sc_wins, "text": within_text_wins, "tie": within_ties},
            "all_wins": {"sc": all_sc_wins, "text": all_text_wins, "tie": all_ties},
        },
        "published_baselines_python": PUBLISHED_BASELINES,
        "leaderboard_comparison": {
            "ndcg_within": {
                "biRNN": 0.169,
                "Neural BoW": 0.279,
                "1D-CNN": 0.341,
                "ElasticSearch": 0.406,
                "Our TF-IDF baseline": avg_nw_text,
                "Our SC-enhanced": avg_nw_sc,
            },
            "ndcg_all": {
                "biRNN": 0.064,
                "Neural BoW": 0.223,
                "1D-CNN": 0.166,
                "ElasticSearch": 0.256,
                "Our TF-IDF baseline": avg_na_text,
                "Our SC-enhanced": avg_na_sc,
            },
        },
        "per_query": [asdict(r) for r in sorted(results, key=lambda r: r.query)],
    }

    # Write outputs
    print("\n[4/5] Writing reports...")
    report_path = RESULTS_DIR / "dataset_eval_v2_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    md = _render_md(report, results)
    md_path = RESULTS_DIR / "dataset_eval_v2_report.md"
    with open(md_path, "w") as f:
        f.write(md)

    # Print summary
    print(f"\n[5/5] Done in {elapsed:.1f}s")
    print(f"  Reports: {report_path}")
    print(f"           {md_path}")

    print(f"\n{'='*70}")
    print(f"RESULTS ({len(results)} queries, {len(corpus):,} corpus)")
    print(f"{'='*70}")
    print(f"\n  NDCG 'Within' (annotated functions only):")
    print(f"    biRNN:                0.169")
    print(f"    Neural BoW:           0.279")
    print(f"    1D-CNN:               0.341")
    print(f"    ElasticSearch:        0.406")
    print(f"    Our TF-IDF baseline:  {avg_nw_text}")
    print(f"    Our SC-enhanced:      {avg_nw_sc}")
    print(f"    SC wins: {within_sc_wins} | Text wins: {within_text_wins} | Ties: {within_ties}")
    print(f"\n  NDCG 'All' (full corpus, top-1000 window):")
    print(f"    biRNN:                0.064")
    print(f"    1D-CNN:               0.166")
    print(f"    Neural BoW:           0.223")
    print(f"    ElasticSearch:        0.256")
    print(f"    Our TF-IDF baseline:  {avg_na_text}")
    print(f"    Our SC-enhanced:      {avg_na_sc}")
    print(f"    SC wins: {all_sc_wins} | Text wins: {all_text_wins} | Ties: {all_ties}")
    print(f"{'='*70}")


def _render_md(report: dict, results: list[QueryResult]) -> str:
    r = report["our_results"]
    lb = report["leaderboard_comparison"]
    lines = [
        "# CodeSearchNet Eval v2: Full-Corpus NDCG vs Published Baselines",
        "",
        f"**Generated:** {report['generated_at']}  ",
        f"**Corpus:** {report['corpus_size']:,} Python functions  ",
        f"**Queries:** {report['queries_evaluated']} evaluated, {report['queries_skipped']} skipped  ",
        f"**Runtime:** {report['elapsed_seconds']}s",
        "",
        "---",
        "",
        "## Leaderboard — NDCG Within (Python)",
        "",
        "NDCG computed only over human-annotated functions. Higher = better.",
        "",
        "| Rank | Model | NDCG Within | Source |",
        "|------|-------|-------------|--------|",
    ]
    within_sorted = sorted(lb["ndcg_within"].items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(within_sorted, 1):
        src = "Husain et al. 2019" if name in PUBLISHED_BASELINES else "**This eval**"
        lines.append(f"| {rank} | {name} | **{score:.4f}** | {src} |")

    lines.extend([
        "",
        "## Leaderboard — NDCG All (Python)",
        "",
        "NDCG computed over all ~457K functions (top-1000 ranking window). Higher = better.",
        "",
        "| Rank | Model | NDCG All | Source |",
        "|------|-------|----------|--------|",
    ])
    all_sorted = sorted(lb["ndcg_all"].items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(all_sorted, 1):
        src = "Husain et al. 2019" if name in PUBLISHED_BASELINES else "**This eval**"
        lines.append(f"| {rank} | {name} | **{score:.4f}** | {src} |")

    lines.extend([
        "",
        "---",
        "",
        "## Win Rates (SC-enhanced vs TF-IDF baseline)",
        "",
        "| Metric | SC wins | Text wins | Ties |",
        "|--------|---------|-----------|------|",
        f"| NDCG Within | {r['within_wins']['sc']} | {r['within_wins']['text']} | {r['within_wins']['tie']} |",
        f"| NDCG All    | {r['all_wins']['sc']} | {r['all_wins']['text']} | {r['all_wins']['tie']} |",
        "",
        "---",
        "",
        "## Per-Query Results",
        "",
        "| Query | Matched | Within(Text) | Within(SC) | All(Text) | All(SC) |",
        "|-------|---------|-------------|-----------|----------|--------|",
    ])
    for q in sorted(results, key=lambda x: x.query):
        lines.append(
            f"| {q.query} | {q.n_matched} | {q.ndcg_within_text:.4f} | "
            f"{q.ndcg_within_sc:.4f} | {q.ndcg_all_text:.4f} | {q.ndcg_all_sc:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
