#!/usr/bin/env bash
# install.sh — Install Bettercontext CLI and global host-agent MCP skills.
#
# Usage:
#   ./install.sh
#   ./install.sh --agent codex
#   ./install.sh --agent claude
#
# Via curl:
#   curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash -s -- --agent codex

set -euo pipefail

REPO_URL="git+https://github.com/roshansingh/bettercontext.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" 2>/dev/null)" 2>/dev/null && pwd 2>/dev/null || echo "")"
TARGET_AGENT="both"
PYTHON_BIN="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)
      if [[ $# -lt 2 ]]; then
        echo "Error: --agent requires a value: codex, claude, or both" >&2
        exit 1
      fi
      TARGET_AGENT="$2"
      shift 2
      ;;
    --python)
      if [[ $# -lt 2 ]]; then
        echo "Error: --python requires a Python executable" >&2
        exit 1
      fi
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,12p' "$0" 2>/dev/null || echo "Usage: install.sh [--agent codex|claude|both] [--python python3]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

case "$TARGET_AGENT" in
  codex|claude|both) ;;
  *)
    echo "Error: --agent must be one of: codex, claude, both" >&2
    exit 1
    ;;
esac

LOCAL_MODE=false
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/pyproject.toml" && -d "$SCRIPT_DIR/source" ]]; then
  LOCAL_MODE=true
fi

echo ""
echo "Installing Bettercontext..."
PIP_USER_ARGS=(--user)
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PIP_USER_ARGS=()
fi

if [[ "$LOCAL_MODE" == true ]]; then
  echo "  Source: local repo ($SCRIPT_DIR)"
  "$PYTHON_BIN" -m pip install "${PIP_USER_ARGS[@]}" --upgrade "$SCRIPT_DIR"
else
  echo "  Source: $REPO_URL"
  "$PYTHON_BIN" -m pip install "${PIP_USER_ARGS[@]}" --upgrade "$REPO_URL"
fi

echo ""
echo "Installing global Bettercontext MCP skills..."
"$PYTHON_BIN" -m source.scripts.install_mcp_skills --scope global --agent "$TARGET_AGENT"

echo ""
echo "Done."
echo ""
echo "Next, in each repo you want indexed:"
echo "  bettercontext-init"
echo ""
echo "For an active local MCP server in that repo:"
echo "  bettercontext-init --serve"
