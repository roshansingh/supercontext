from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_MCP_NAME = "supercontext"
LEGACY_MCP_NAME = "bettercontext"
DEFAULT_MCP_URL = "http://127.0.0.1:3845/mcp"
SUPPORTED_AGENTS = ("codex", "claude")


@dataclass(frozen=True)
class RegistrationCommand:
    agent: str
    executable: str
    remove_command: tuple[str, ...]
    add_command: tuple[str, ...]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the local SuperContext MCP server with host agents."
    )
    parser.add_argument(
        "--agent",
        choices=[*SUPPORTED_AGENTS, "both"],
        default="both",
        help="Register Codex, Claude Code, or both. Defaults to both.",
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_MCP_NAME,
        help=f"MCP server name. Defaults to {DEFAULT_MCP_NAME}.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MCP_URL,
        help=f"MCP server URL. Defaults to {DEFAULT_MCP_URL}.",
    )
    parser.add_argument(
        "--on-error",
        choices=["warn", "error"],
        default="warn",
        help=(
            "Warn or error when a host CLI is missing or registration fails. "
            "Defaults to warn."
        ),
    )
    parser.add_argument(
        "--missing",
        choices=["warn", "error"],
        dest="on_error",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print registration commands without running them.",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="Remove the MCP registration and do not add it again.",
    )
    args = parser.parse_args()

    if not args.name.strip():
        parser.error("--name must not be empty")
    if not args.url.strip():
        parser.error("--url must not be empty")
    if not _is_http_url(args.url):
        parser.error("--url must be an HTTP(S) URL with a host")

    agents = SUPPORTED_AGENTS if args.agent == "both" else (args.agent,)
    for agent in agents:
        command = _registration_command(agent, name=args.name, url=args.url)
        if shutil.which(command.executable) is None:
            message = (
                f"{command.executable!r} CLI not found; skipped {agent} "
                "MCP registration"
            )
            if args.on_error == "error":
                parser.error(message)
            print(f"warning: {message}")
            continue

        if args.dry_run:
            print(
                f"would remove existing {agent} MCP registration: "
                f"{_join(command.remove_command)}"
            )
            if _should_remove_legacy_name(args.name, args.remove):
                legacy_command = _registration_command(agent, name=LEGACY_MCP_NAME, url=args.url)
                print(
                    f"would remove legacy {agent} MCP registration: "
                    f"{_join(legacy_command.remove_command)}"
                )
            if not args.remove:
                print(f"would add {agent} MCP registration: {_join(command.add_command)}")
            continue

        try:
            remove_result = subprocess.run(
                command.remove_command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            _handle_registration_failure(
                parser,
                args.on_error,
                agent,
                command.remove_command,
                exc,
            )
            continue
        if args.remove:
            remove_returncode = getattr(remove_result, "returncode", 0)
            if isinstance(remove_returncode, int) and remove_returncode != 0:
                _handle_registration_failure(
                    parser,
                    args.on_error,
                    agent,
                    command.remove_command,
                    subprocess.CalledProcessError(remove_returncode, command.remove_command),
                )
                continue
            print(f"ran remove command for {agent} MCP server {args.name!r}")
            continue
        if _should_remove_legacy_name(args.name, args.remove):
            legacy_command = _registration_command(agent, name=LEGACY_MCP_NAME, url=args.url)
            _remove_legacy_registration(agent, legacy_command.remove_command)
        try:
            subprocess.run(command.add_command, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            _handle_registration_failure(
                parser,
                args.on_error,
                agent,
                command.add_command,
                exc,
            )
            continue
        print(f"registered {agent} MCP server {args.name!r}: {args.url}")


def _should_remove_legacy_name(name: str, remove: bool) -> bool:
    return not remove and name == DEFAULT_MCP_NAME


def _remove_legacy_registration(agent: str, command: tuple[str, ...]) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(f"warning: legacy {agent} MCP cleanup failed ({exc}): {_join(command)}")
        return
    returncode = getattr(result, "returncode", 0)
    if isinstance(returncode, int) and returncode == 0:
        print(f"removed legacy {agent} MCP registration {LEGACY_MCP_NAME!r}")


def _registration_command(agent: str, *, name: str, url: str) -> RegistrationCommand:
    if agent == "codex":
        return RegistrationCommand(
            agent=agent,
            executable="codex",
            remove_command=("codex", "mcp", "remove", name),
            add_command=("codex", "mcp", "add", name, "--url", url),
        )
    if agent == "claude":
        return RegistrationCommand(
            agent=agent,
            executable="claude",
            remove_command=("claude", "mcp", "remove", "--scope", "user", name),
            add_command=(
                "claude",
                "mcp",
                "add",
                "--scope",
                "user",
                "--transport",
                "http",
                name,
                url,
            ),
        )
    raise ValueError(f"Unsupported agent: {agent}")


def _join(command: tuple[str, ...]) -> str:
    return shlex.join(command)


def _handle_registration_failure(
    parser: argparse.ArgumentParser,
    on_error: str,
    agent: str,
    command: tuple[str, ...],
    exc: OSError | subprocess.CalledProcessError,
) -> None:
    if isinstance(exc, subprocess.CalledProcessError):
        detail = f"exit code {exc.returncode}"
    else:
        detail = str(exc)
    message = f"{agent} MCP registration failed ({detail}): {_join(command)}"
    if on_error == "error":
        parser.error(message)
    print(f"warning: {message}")


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


if __name__ == "__main__":
    main()
