from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess

from source.kg.org.workspace import DiscoveredRepo


@dataclass(frozen=True)
class GitHubCliRepoProvider:
    org: str
    limit: int = 1000
    include_archived: bool = False
    clone_protocol: str = "https"

    def list_repos(self) -> list[DiscoveredRepo]:
        command = [
            "gh",
            "repo",
            "list",
            self.org,
            "--limit",
            str(self.limit),
            "--json",
            "name,nameWithOwner,sshUrl,url,isArchived,defaultBranchRef",
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("GitHub org discovery requires the 'gh' CLI to be installed and authenticated") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or f"exit code {exc.returncode}"
            raise RuntimeError(f"GitHub org discovery failed for {self.org}: {detail}") from exc
        return _parse_repo_rows(result.stdout, include_archived=self.include_archived, clone_protocol=self.clone_protocol)


def _parse_repo_rows(raw_json: str, include_archived: bool, clone_protocol: str) -> list[DiscoveredRepo]:
    try:
        rows = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub CLI returned invalid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise ValueError("GitHub CLI repo JSON must be a list")
    repos: list[DiscoveredRepo] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"GitHub CLI repo row {index} must be an object")
        name = _required_str(row, "name", index)
        full_name = _required_str(row, "nameWithOwner", index)
        archived = _required_bool(row, "isArchived", index)
        if archived and not include_archived:
            continue
        branch_ref = row.get("defaultBranchRef")
        if branch_ref is None:
            continue
        elif isinstance(branch_ref, dict):
            name_value = branch_ref.get("name")
            if not isinstance(name_value, str) or not name_value.strip():
                continue
            default_branch = name_value
        else:
            raise ValueError(f"GitHub CLI repo row {index} field defaultBranchRef must be an object or null")
        clone_url = _clone_url(row, clone_protocol, index)
        repos.append(
            DiscoveredRepo(
                name=name,
                full_name=full_name,
                clone_url=clone_url,
                default_branch=default_branch,
                archived=archived,
            )
        )
    return repos


def _clone_url(row: dict[str, object], clone_protocol: str, index: int) -> str:
    if clone_protocol == "ssh":
        return _required_str(row, "sshUrl", index)
    if clone_protocol == "https":
        return _required_str(row, "url", index)
    raise ValueError("clone_protocol must be 'ssh' or 'https'")


def _required_str(row: dict[str, object], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"GitHub CLI repo row {index} field {field} must be a non-empty string")
    return value


def _required_bool(row: dict[str, object], field: str, index: int) -> bool:
    value = row.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"GitHub CLI repo row {index} field {field} must be a boolean")
    return value
