from __future__ import annotations

import argparse
import os
import shutil
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Iterable


SKILL_NAME = "supercontext-mcp"
TEMPLATE_ROOT = "mcp_skill_templates"
SUPPORTED_AGENTS = ("codex", "claude")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install SuperContext MCP host-agent skills.")
    parser.add_argument(
        "--agent",
        choices=[*SUPPORTED_AGENTS, "both"],
        default="both",
        help="Install the Codex skill, Claude Code skill, or both. Defaults to both.",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "global"],
        default="project",
        help="Install into a project-local skill directory or a global user skill directory. Defaults to project.",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Project directory for --scope project. Defaults to the current directory.",
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME") or "~/.codex",
        help="Codex home for --scope global. Defaults to CODEX_HOME or ~/.codex.",
    )
    parser.add_argument(
        "--claude-home",
        default=os.environ.get("CLAUDE_HOME") or "~/.claude",
        help="Claude Code home for --scope global. Defaults to CLAUDE_HOME or ~/.claude.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print target paths without writing files.")
    args = parser.parse_args()
    codex_home = _non_empty_home(parser, args.codex_home, "--codex-home")
    claude_home = _non_empty_home(parser, args.claude_home, "--claude-home")

    agents = SUPPORTED_AGENTS if args.agent == "both" else (args.agent,)
    for agent in agents:
        source = _template_dir(agent)
        target = _target_dir(
            agent,
            scope=args.scope,
            project=Path(args.project),
            codex_home=codex_home,
            claude_home=claude_home,
        )
        if args.dry_run:
            print(f"would install {agent} skill: {target}")
            continue
        _copy_resource_tree(source, target, reject_symlink_ancestors=args.scope == "project")
        print(f"installed {agent} skill: {target}")


def _template_dir(agent: str) -> Traversable:
    root = resources.files("source.kg.product")
    source = root.joinpath(TEMPLATE_ROOT, agent, SKILL_NAME)
    if not source.is_dir():
        raise RuntimeError(f"Missing installable SuperContext MCP skill template for {agent!r}")
    return source


def _non_empty_home(parser: argparse.ArgumentParser, value: str, flag: str) -> Path:
    if not value.strip():
        parser.error(f"{flag} must not be empty")
    return Path(value).expanduser()


def _target_dir(
    agent: str,
    *,
    scope: str,
    project: Path,
    codex_home: Path,
    claude_home: Path,
) -> Path:
    if scope == "project":
        base = project.expanduser().resolve()
        if agent == "codex":
            return base / ".codex" / "skills" / SKILL_NAME
        if agent == "claude":
            return base / ".claude" / "skills" / SKILL_NAME
    elif scope == "global":
        if agent == "codex":
            return codex_home / "skills" / SKILL_NAME
        if agent == "claude":
            return claude_home / "skills" / SKILL_NAME
    raise ValueError(f"Unsupported agent/scope combination: {agent}/{scope}")


def _copy_resource_tree(source: Traversable, target: Path, *, reject_symlink_ancestors: bool) -> None:
    if reject_symlink_ancestors:
        _reject_symlink_skill_path(target)
    if target.is_symlink() or target.exists():
        if target.is_symlink() or not target.is_dir():
            raise RuntimeError(f"Cannot replace non-directory skill target: {target}")
        shutil.rmtree(target)
    for item in _walk_resources(source):
        relative = Path(*item.name_parts)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item.resource.read_bytes())


class _ResourceFile:
    def __init__(self, *, resource: Traversable, name_parts: tuple[str, ...]) -> None:
        self.resource = resource
        self.name_parts = name_parts


def _walk_resources(
    source: Traversable,
    parts: tuple[str, ...] = (),
) -> Iterable[_ResourceFile]:
    for item in source.iterdir():
        item_parts = (*parts, item.name)
        if item.is_dir():
            yield from _walk_resources(item, item_parts)
        elif item.is_file():
            yield _ResourceFile(resource=item, name_parts=item_parts)


def _reject_symlink_skill_path(target: Path) -> None:
    guard_root = target.parents[2] if len(target.parents) >= 3 else target.parent
    current = target
    while current != guard_root:
        if current.is_symlink():
            raise RuntimeError(f"Cannot install through symlinked skill path: {current}")
        current = current.parent


if __name__ == "__main__":
    main()
