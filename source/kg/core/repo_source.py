from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


IGNORED_DIRS = {
    ".git",
    ".idea",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".vercel",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}

TYPESCRIPT_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}


@dataclass(frozen=True)
class RepoSnapshot:
    root: Path
    name: str
    owner: str
    commit_sha: str
    python_files: tuple[Path, ...]
    typescript_files: tuple[Path, ...]


def discover_repo(repo_path: str | Path) -> RepoSnapshot:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repo path does not exist: {root}")

    source_files = tuple(sorted(_iter_source_files(root)))
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha=_git_commit_sha(root),
        python_files=tuple(path for path in source_files if path.suffix == ".py"),
        typescript_files=tuple(path for path in source_files if _is_typescript_file(path)),
    )


def _iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix == ".py" or _is_typescript_file(path):
            files.append(path)
    return files


def _is_typescript_file(path: Path) -> bool:
    if path.name.endswith(".d.ts"):
        return False
    return path.suffix in TYPESCRIPT_EXTENSIONS


def _git_commit_sha(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "working-tree"
    return result.stdout.strip() or "working-tree"
