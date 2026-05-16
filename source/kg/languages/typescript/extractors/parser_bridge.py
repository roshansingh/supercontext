from __future__ import annotations

import json
import subprocess
from pathlib import Path

from source.kg.core.models import JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import ExtractionContext


def parse_typescript_repo(repo: RepoSnapshot, ctx: ExtractionContext | None = None) -> dict[str, JsonObject]:
    cache_key = f"{repo.root}:{repo.commit_sha}"
    if ctx is not None:
        cached = ctx.js_ts_parsed_files.get(cache_key)
        if isinstance(cached, dict):
            return cached

    parsed = _parse_typescript_repo_uncached(repo)
    if ctx is not None:
        ctx.js_ts_parsed_files[cache_key] = parsed
    return parsed


def _parse_typescript_repo_uncached(repo: RepoSnapshot) -> dict[str, JsonObject]:
    parser_path = Path(__file__).with_name("ts_parser.mjs")
    payload = {
        "repoRoot": str(repo.root),
        "files": [str(path.relative_to(repo.root)) for path in repo.typescript_files],
    }
    try:
        result = subprocess.run(
            ["node", str(parser_path)],
            input=json.dumps(payload),
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or str(exc)
        raise RuntimeError(f"TypeScript parser bridge failed: {detail}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("TypeScript parser bridge failed: node executable was not found") from exc

    try:
        loaded = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TypeScript parser bridge returned invalid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError("TypeScript parser bridge returned a non-object payload")
    return loaded
