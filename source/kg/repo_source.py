from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


IGNORED_DIRS = {
    ".git",
    ".idea",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


@dataclass(frozen=True)
class RepoSnapshot:
    root: Path
    name: str
    owner: str
    commit_sha: str
    python_files: tuple[Path, ...]


def discover_repo(repo_path: str | Path) -> RepoSnapshot:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repo path does not exist: {root}")

    python_files = tuple(sorted(_iter_python_files(root)))
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha=_git_commit_sha(root),
        python_files=python_files,
    )


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


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

