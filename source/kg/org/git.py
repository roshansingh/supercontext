from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from source.kg.org.workspace import DiscoveredRepo


MANAGED_REPO_MARKER = ".supercontext-managed-repo"


class GitClient:
    def __init__(self, timeout_seconds: int = 300) -> None:
        self.timeout_seconds = timeout_seconds

    def sync_repo(self, repo: DiscoveredRepo, destination: Path) -> str:
        destination = destination.expanduser().resolve()
        if destination.exists():
            if _is_incomplete_managed_cache_clone(destination):
                shutil.rmtree(destination)
                self._clone(repo, destination)
            else:
                _ensure_managed_repo(destination, repo)
                self._fetch(repo, destination)
        else:
            self._clone(repo, destination)
        _write_marker(destination, repo)
        return self._head(destination)

    def _clone(self, repo: DiscoveredRepo, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            repo.default_branch,
            repo.clone_url,
            str(destination),
        ]
        try:
            _run(command, timeout_seconds=self.timeout_seconds)
        except Exception:
            if destination.exists() and not (destination / MANAGED_REPO_MARKER).exists():
                shutil.rmtree(destination)
            raise

    def _fetch(self, repo: DiscoveredRepo, destination: Path) -> None:
        _run(["git", "-C", str(destination), "remote", "set-url", "origin", repo.clone_url], timeout_seconds=self.timeout_seconds)
        _run(["git", "-C", str(destination), "fetch", "--depth", "1", "origin", repo.default_branch], timeout_seconds=self.timeout_seconds)
        _run(["git", "-C", str(destination), "checkout", "--force", "FETCH_HEAD"], timeout_seconds=self.timeout_seconds)

    def _head(self, destination: Path) -> str:
        result = _run(["git", "-C", str(destination), "rev-parse", "HEAD"], timeout_seconds=self.timeout_seconds)
        return result.stdout.strip()


def _ensure_managed_repo(destination: Path, repo: DiscoveredRepo) -> None:
    marker = destination / MANAGED_REPO_MARKER
    if not marker.exists():
        raise ValueError(f"Refusing to modify unmanaged repository cache path: {destination}")
    recorded = marker.read_text(encoding="utf-8").strip()
    if recorded and recorded != repo.full_name:
        raise ValueError(
            f"Refusing to reuse cache path {destination} for {repo.full_name}; "
            f"it is marked for {recorded}"
        )


def _write_marker(destination: Path, repo: DiscoveredRepo) -> None:
    (destination / MANAGED_REPO_MARKER).write_text(repo.full_name, encoding="utf-8")


def _is_incomplete_managed_cache_clone(destination: Path) -> bool:
    if (destination / MANAGED_REPO_MARKER).exists():
        return False
    return (
        destination.parent.name == "repos"
        and (destination.parent.parent / "config.json").exists()
        and (destination / ".git").exists()
    )


def _run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout_seconds)
