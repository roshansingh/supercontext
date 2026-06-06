from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.kg.org.workspace import (
    DiscoveredRepo,
    build_org,
    init_org,
    load_org_state,
    sync_org,
)


class OrgWorkspaceTest(unittest.TestCase):
    def test_init_org_writes_portable_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            resolved_home = home.resolve()

            config = init_org(provider="github", org="Acme", home=home, include=("services/*",))

            config_path = home / "config.json"
            self.assertTrue(config_path.exists())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["provider"], "github")
            self.assertEqual(data["org"], "Acme")
            self.assertEqual(data["include"], ["services/*"])
            self.assertEqual(data["exclude"], [])
            self.assertEqual(config.snapshot_dir, resolved_home / "kg")

    def test_sync_org_clones_new_repos_into_managed_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            resolved_home = home.resolve()
            init_org(provider="github", org="Acme", home=home)
            provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="git@github.com:Acme/api.git",
                        default_branch="main",
                    ),
                    DiscoveredRepo(
                        name="worker",
                        full_name="Acme/worker",
                        clone_url="git@github.com:Acme/worker.git",
                        default_branch="trunk",
                    ),
                ]
            )
            git = _FakeGitClient({"Acme/api": "aaa111", "Acme/worker": "bbb222"})

            result = sync_org(home, provider=provider, git_client=git)

            self.assertEqual(result.repo_count, 2)
            self.assertEqual(result.changed_count, 2)
            self.assertEqual(
                [(operation, url, branch) for operation, url, _, branch in git.operations],
                [
                    ("clone", "git@github.com:Acme/api.git", "main"),
                    ("clone", "git@github.com:Acme/worker.git", "trunk"),
                ],
            )
            self.assertEqual(git.operations[0][2], resolved_home / "repos" / "api")
            self.assertEqual(git.operations[1][2], resolved_home / "repos" / "worker")
            state = load_org_state(home)
            self.assertEqual({repo.full_name for repo in state.repos}, {"Acme/api", "Acme/worker"})
            self.assertEqual({repo.commit_sha for repo in state.repos}, {"aaa111", "bbb222"})

    def test_sync_org_fetches_existing_repos_and_tracks_changed_heads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            resolved_home = home.resolve()
            init_org(provider="github", org="Acme", home=home)
            provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="git@github.com:Acme/api.git",
                        default_branch="main",
                    )
                ]
            )
            first_git = _FakeGitClient({"Acme/api": "aaa111"})
            sync_org(home, provider=provider, git_client=first_git)
            second_git = _FakeGitClient({"Acme/api": "ccc333"})

            result = sync_org(home, provider=provider, git_client=second_git)

            self.assertEqual(result.repo_count, 1)
            self.assertEqual(result.changed_count, 1)
            self.assertEqual(
                second_git.operations,
                [("fetch", "git@github.com:Acme/api.git", resolved_home / "repos" / "api", "main")],
            )
            state = load_org_state(home)
            self.assertEqual(state.repos[0].commit_sha, "ccc333")

    def test_sync_org_continues_after_repo_failure_and_preserves_previous_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            init_org(provider="github", org="Acme", home=home)
            first_provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="https://github.com/Acme/api",
                        default_branch="main",
                    )
                ]
            )
            sync_org(home, provider=first_provider, git_client=_FakeGitClient({"Acme/api": "aaa111"}))
            second_provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="https://github.com/Acme/api",
                        default_branch="main",
                    ),
                    DiscoveredRepo(
                        name="worker",
                        full_name="Acme/worker",
                        clone_url="https://github.com/Acme/worker",
                        default_branch="main",
                    ),
                ]
            )

            result = sync_org(
                home,
                provider=second_provider,
                git_client=_FailingGitClient({"Acme/api": "network timeout", "Acme/worker": "bbb222"}),
            )

            self.assertEqual(result.repo_count, 2)
            self.assertEqual(result.changed_count, 1)
            self.assertEqual(result.unchanged_count, 0)
            self.assertEqual(result.failed_count, 1)
            self.assertEqual(result.errors[0]["repo"], "Acme/api")
            state = load_org_state(home)
            self.assertEqual({repo.full_name for repo in state.repos}, {"Acme/api", "Acme/worker"})
            self.assertEqual({repo.commit_sha for repo in state.repos}, {"aaa111", "bbb222"})
            self.assertEqual(state.last_sync_errors[0]["repo"], "Acme/api")

    def test_build_org_skips_when_commit_fingerprint_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            resolved_home = home.resolve()
            init_org(provider="github", org="Acme", home=home)
            provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="git@github.com:Acme/api.git",
                        default_branch="main",
                    )
                ]
            )
            sync_org(home, provider=provider, git_client=_FakeGitClient({"Acme/api": "aaa111"}))
            calls: list[tuple[list[Path], Path]] = []

            first = build_org(home, build_multi_kg_func=_recording_builder(calls))
            second = build_org(home, build_multi_kg_func=_recording_builder(calls))

            self.assertFalse(first.skipped)
            self.assertTrue(second.skipped)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], [resolved_home / "repos" / "api"])
            self.assertEqual(calls[0][1], resolved_home / "kg")

    def test_build_org_rebuilds_when_force_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            init_org(provider="github", org="Acme", home=home)
            provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="git@github.com:Acme/api.git",
                        default_branch="main",
                    )
                ]
            )
            sync_org(home, provider=provider, git_client=_FakeGitClient({"Acme/api": "aaa111"}))
            calls: list[tuple[list[Path], Path]] = []

            build_org(home, build_multi_kg_func=_recording_builder(calls))
            forced = build_org(home, force=True, build_multi_kg_func=_recording_builder(calls))

            self.assertFalse(forced.skipped)
            self.assertEqual(len(calls), 2)

    def test_build_org_forwards_progress_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            init_org(provider="github", org="Acme", home=home)
            provider = _StaticRepoProvider(
                [
                    DiscoveredRepo(
                        name="api",
                        full_name="Acme/api",
                        clone_url="https://github.com/Acme/api",
                        default_branch="main",
                    )
                ]
            )
            sync_org(home, provider=provider, git_client=_FakeGitClient({"Acme/api": "aaa111"}))
            progress_calls: list[tuple[int, int, str]] = []
            kwargs_seen: list[object] = []

            def build(repo_paths: list[Path], output_dir: Path, **kwargs):
                kwargs_seen.append(kwargs.get("progress"))
                self.assertEqual(kwargs.get("repo_owner"), "Acme")
                kwargs["progress"](1, 1, repo_paths[0])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "manifest.json").write_text("{}", encoding="utf-8")
                return {"repo_count": len(repo_paths)}

            build_org(
                home,
                build_multi_kg_func=build,
                progress=lambda index, total, path: progress_calls.append((index, total, path.name)),
            )

            self.assertEqual(len(kwargs_seen), 1)
            self.assertEqual(progress_calls, [(1, 1, "api")])


def _recording_builder(calls: list[tuple[list[Path], Path]]):
    def build(repo_paths: list[Path], output_dir: Path, **kwargs):
        calls.append((repo_paths, output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "manifest.json").write_text("{}", encoding="utf-8")
        return {"repo_count": len(repo_paths)}

    return build


class _StaticRepoProvider:
    def __init__(self, repos: list[DiscoveredRepo]) -> None:
        self._repos = repos

    def list_repos(self) -> list[DiscoveredRepo]:
        return list(self._repos)


class _FakeGitClient:
    def __init__(self, heads: dict[str, str]) -> None:
        self._heads = heads
        self.operations: list[tuple[str, str, Path, str]] = []

    def sync_repo(self, repo: DiscoveredRepo, destination: Path) -> str:
        operation = "fetch" if destination.exists() else "clone"
        self.operations.append((operation, repo.clone_url, destination, repo.default_branch))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / ".supercontext-managed-repo").write_text(repo.full_name, encoding="utf-8")
        return self._heads[repo.full_name]


class _FailingGitClient:
    def __init__(self, outcomes: dict[str, str]) -> None:
        self._outcomes = outcomes

    def sync_repo(self, repo: DiscoveredRepo, destination: Path) -> str:
        outcome = self._outcomes[repo.full_name]
        if "timeout" in outcome:
            raise TimeoutError(outcome)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / ".supercontext-managed-repo").write_text(repo.full_name, encoding="utf-8")
        return outcome


if __name__ == "__main__":
    unittest.main()
