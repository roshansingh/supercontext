from __future__ import annotations

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
    cli_path = configured_path or which("claude")
    if not cli_path:
        raise RuntimeError(
            "Claude CLI was not found on PATH. Install/configure the Claude CLI, "
            "or pass --claude-cli-path /path/to/claude."
        )
    return cli_path
