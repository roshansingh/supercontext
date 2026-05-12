from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from source.kg.query.snapshot import KgSnapshot


REQUIRED_SNAPSHOT_FILES = ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl", "manifest.json")
DEFAULT_ORGS_ROOT = "~/work/orgs"
DEFAULT_SNAPSHOTS_ROOT = "data/kg_runs"


@dataclass(frozen=True)
class QuerySpec:
    name: str
    description: str
    runner: Callable[[KgSnapshot, dict[str, Any]], Any]


def streamlit_available() -> bool:
    return importlib.util.find_spec("streamlit") is not None


def resolve_orgs_root(value: str | None = None) -> Path:
    root = value or os.environ.get("SUPERCONTEXT_ORGS_ROOT") or DEFAULT_ORGS_ROOT
    return Path(root).expanduser()


def discover_orgs(root: Path) -> list[str]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and _contains_repo_dir(path))


def _contains_repo_dir(path: Path) -> bool:
    return any(child.is_dir() for child in path.iterdir())


def discover_snapshots(root: Path = Path(DEFAULT_SNAPSHOTS_ROOT)) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir() and is_snapshot_dir(path))


def is_snapshot_dir(path: Path) -> bool:
    return path.is_dir() and all((path / filename).exists() for filename in REQUIRED_SNAPSHOT_FILES)


def build_multi_kg_hint(orgs_root: Path, org_name: str | None = None) -> str:
    repo_arg = f'"{orgs_root / (org_name or "<org>") / "<repo>"}"'
    return (
        "python -m source.scripts.build_multi_kg "
        f"--repo {repo_arg} "
        f"--out data/kg_runs/{org_name or '<snapshot_name>'}"
    )


def query_specs() -> dict[str, QuerySpec]:
    return {
        "summary": QuerySpec(
            name="summary",
            description="Counts by entity kind and predicate, plus coverage rows.",
            runner=lambda kg, args: kg.summary(),
        ),
        "find_callers": QuerySpec(
            name="find_callers",
            description="Find symbols that call a target symbol.",
            runner=lambda kg, args: kg.find_callers(
                args["symbol"],
                limit=args["limit"],
                path=args.get("path") or None,
                line=args.get("line"),
                include_all=args["include_all"],
            ),
        ),
        "modules_importing": QuerySpec(
            name="modules_importing",
            description="Find modules importing a package.",
            runner=lambda kg, args: kg.modules_importing(args["package"], limit=args["limit"]),
        ),
        "top_dependencies": QuerySpec(
            name="top_dependencies",
            description="Rank external dependencies by importer count.",
            runner=lambda kg, args: kg.top_dependencies(
                limit=args["limit"],
                exclude_stdlib=not args["include_stdlib"],
                exclude_unknown=not args["include_unknown"],
            ),
        ),
        "blast_radius": QuerySpec(
            name="blast_radius",
            description="Traverse static CALLS edges from a symbol.",
            runner=lambda kg, args: kg.blast_radius(
                args["symbol"],
                depth=args["depth"],
                limit=args["limit"],
                path=args.get("path") or None,
                line=args.get("line"),
                include_all=args["include_all"],
            ),
        ),
        "lookup_symbol": QuerySpec(
            name="lookup_symbol",
            description="Resolve a symbol name to candidates or one exact symbol.",
            runner=lambda kg, args: kg.lookup_symbol(
                args["symbol"],
                limit=args["limit"],
                path=args.get("path") or None,
                line=args.get("line"),
            ),
        ),
    }


def main() -> None:
    if not streamlit_available():
        print("Streamlit is optional. Install it with `pip install streamlit`.", file=sys.stderr)
        return

    import streamlit as st

    st.set_page_config(page_title="Supercontext KG Explorer", layout="wide")
    st.title("Supercontext KG Explorer")
    st.caption("Thin local UI over existing JSONL KG snapshots. No LLM calls and no auto-build in v1.")

    orgs_root = resolve_orgs_root(st.sidebar.text_input("Orgs root", str(resolve_orgs_root())))
    orgs = discover_orgs(orgs_root)
    selected_org = st.sidebar.selectbox("Org hint", ["<none>"] + orgs)

    snapshots_root = Path(st.sidebar.text_input("Snapshots root", DEFAULT_SNAPSHOTS_ROOT)).expanduser()
    snapshots = discover_snapshots(snapshots_root)
    if not snapshots:
        st.warning("No complete KG snapshots found.")
        st.code(build_multi_kg_hint(orgs_root, None if selected_org == "<none>" else selected_org), language="bash")
        return

    snapshot_labels = [str(path) for path in snapshots]
    snapshot_path = Path(st.sidebar.selectbox("Snapshot", snapshot_labels))
    specs = query_specs()
    query_name = st.selectbox(
        "Query surface",
        list(specs),
        format_func=lambda name: f"{name} - {specs[name].description}",
    )
    args = _render_args(st, query_name)

    if st.button("Run query", type="primary"):
        missing_arg = _missing_required_arg(query_name, args)
        if missing_arg:
            st.warning(f"Enter {missing_arg} before running this query.")
            return
        kg = _load_snapshot(str(snapshot_path))
        result = specs[query_name].runner(kg, args)
        st.json(_jsonable(result))


def _render_args(st: Any, query_name: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    if query_name in {"find_callers", "blast_radius", "lookup_symbol"}:
        args["symbol"] = st.text_input("Symbol", "")
        args["path"] = st.text_input("Optional source path", "")
        line = st.number_input("Optional line number", min_value=0, value=0, step=1)
        args["line"] = int(line) if line else None
        args["limit"] = int(st.number_input("Limit", min_value=1, max_value=100, value=25, step=1))
        if query_name in {"find_callers", "blast_radius"}:
            args["include_all"] = st.checkbox("Include all ambiguous candidates", value=False)
        if query_name == "blast_radius":
            args["depth"] = int(st.number_input("Depth", min_value=1, max_value=6, value=2, step=1))
    elif query_name == "modules_importing":
        args["package"] = st.text_input("Package", "")
        args["limit"] = int(st.number_input("Limit", min_value=1, max_value=100, value=25, step=1))
    elif query_name == "top_dependencies":
        args["limit"] = int(st.number_input("Limit", min_value=1, max_value=100, value=25, step=1))
        args["include_stdlib"] = st.checkbox("Include stdlib / Node builtins", value=False)
        args["include_unknown"] = st.checkbox("Include unknown imports", value=False)
    return args


def _load_snapshot(snapshot_path: str) -> KgSnapshot:
    return KgSnapshot(snapshot_path)


if streamlit_available():
    import streamlit as _streamlit

    _load_snapshot = _streamlit.cache_resource(_load_snapshot)


def _missing_required_arg(query_name: str, args: dict[str, Any]) -> str | None:
    if query_name in {"find_callers", "blast_radius", "lookup_symbol"} and not str(args.get("symbol", "")).strip():
        return "a symbol"
    if query_name == "modules_importing" and not str(args.get("package", "")).strip():
        return "a package"
    return None


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
