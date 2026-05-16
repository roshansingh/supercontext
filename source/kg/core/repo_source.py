from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from source.kg.languages.file_matchers import REGISTERED_LANGUAGE_FILES
from source.kg.languages.types import LanguageFileMatcher


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

@dataclass(frozen=True, init=False, eq=False)
class RepoSnapshot:
    root: Path
    name: str
    owner: str
    commit_sha: str
    files_by_language: dict[str, tuple[Path, ...]]

    def __init__(
        self,
        root: Path,
        name: str,
        owner: str,
        commit_sha: str,
        files_by_language: dict[str, tuple[Path, ...]] | None = None,
        python_files: tuple[Path, ...] | None = None,
        typescript_files: tuple[Path, ...] | None = None,
    ) -> None:
        if files_by_language is None:
            files_by_language = {
                "python": python_files or (),
                "typescript": typescript_files or (),
            }
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "commit_sha", commit_sha)
        object.__setattr__(
            self,
            "files_by_language",
            {language: tuple(paths) for language, paths in files_by_language.items()},
        )

    @property
    def python_files(self) -> tuple[Path, ...]:
        return self.files_by_language.get("python", ())

    @property
    def typescript_files(self) -> tuple[Path, ...]:
        return self.files_by_language.get("typescript", ())

    def __hash__(self) -> int:
        return hash((self.root, self.name, self.owner, self.commit_sha))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RepoSnapshot):
            return NotImplemented
        return (
            self.root,
            self.name,
            self.owner,
            self.commit_sha,
        ) == (
            other.root,
            other.name,
            other.owner,
            other.commit_sha,
        )


def discover_repo(
    repo_path: str | Path,
    language_files: tuple[LanguageFileMatcher, ...] = REGISTERED_LANGUAGE_FILES,
) -> RepoSnapshot:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repo path does not exist: {root}")

    files_by_language = _files_by_language(root, language_files)
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha=_git_commit_sha(root),
        files_by_language=files_by_language,
    )


def _iter_source_files(root: Path) -> list[Path]:
    return sorted({path for paths in _files_by_language(root).values() for path in paths})


def _files_by_language(
    root: Path,
    language_files: tuple[LanguageFileMatcher, ...] = REGISTERED_LANGUAGE_FILES,
) -> dict[str, tuple[Path, ...]]:
    buckets: dict[str, list[Path]] = {language.name: [] for language in language_files}
    candidate_extensions = {extension for language in language_files for extension in language.file_extensions}
    candidate_manifest_files = {filename for language in language_files for filename in language.manifest_files}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix not in candidate_extensions and path.name not in candidate_manifest_files:
            continue
        for language in language_files:
            if language.matches_file(path):
                buckets.setdefault(language.name, []).append(path)
                break
    return {language: tuple(sorted(paths)) for language, paths in buckets.items()}


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
