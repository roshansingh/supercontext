from __future__ import annotations

import os
from pathlib import Path
from shutil import which


DISALLOWED_CLAUDE_TOOLS = (
    "Agent",
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "LS",
    "Read",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
)

DEFAULT_CLAUDE_PERMISSION_MODE = "default"


def resolve_claude_cli_path(configured_path: str | None = None) -> str:
    cli_path = _resolve_configured_cli_path(configured_path) if configured_path else which("claude")
    if not cli_path:
        raise RuntimeError(
            "Claude CLI was not found on PATH. Install/configure the Claude CLI, "
            "or pass --claude-cli-path /path/to/claude."
        )
    return cli_path


def _resolve_configured_cli_path(configured_path: str) -> str:
    cli_path = which(configured_path) or configured_path
    path = Path(cli_path).expanduser()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"Configured Claude CLI path is not executable: {configured_path}")
    return str(path)
