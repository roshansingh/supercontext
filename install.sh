#!/usr/bin/env bash
# install.sh — Install SuperContext CLI, host MCP registration, and global host-agent MCP skills.
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

usage() {
  cat <<'EOF'
install.sh — Install SuperContext CLI, host MCP registration, and global host-agent MCP skills.

Usage:
  ./install.sh
  ./install.sh --agent codex
  ./install.sh --agent claude
  ./install.sh --agent both --python python3

Via curl:
  curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/roshansingh/bettercontext/main/install.sh | bash -s -- --agent codex
EOF
}

REPO_URL="git+https://github.com/roshansingh/bettercontext.git"
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd 2>/dev/null || echo "")"
fi
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
      usage
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

if [[ -z "${SUPERCONTEXT_HOME:-}" ]]; then
  USER_HOME="${HOME:-}"
  if [[ -z "$USER_HOME" ]]; then
    USER_HOME="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path

print(Path.home())
PY
)"
  fi
  SUPERCONTEXT_HOME="$USER_HOME/.supercontext"
fi

LOCAL_MODE=false
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/pyproject.toml" && -d "$SCRIPT_DIR/source" ]]; then
  LOCAL_MODE=true
fi

VENV_DIR="$SUPERCONTEXT_HOME/venv"
echo ""
echo "Preparing SuperContext environment: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
INSTALL_PYTHON="$VENV_DIR/bin/python"
SCRIPTS_DIR="$VENV_DIR/bin"
"$INSTALL_PYTHON" -m pip install --upgrade pip

echo ""
echo "Installing SuperContext..."
if [[ "$LOCAL_MODE" == true ]]; then
  echo "  Source: local repo ($SCRIPT_DIR)"
  "$INSTALL_PYTHON" -m pip install --upgrade "$SCRIPT_DIR"
else
  echo "  Source: $REPO_URL"
  "$INSTALL_PYTHON" -m pip install --upgrade "$REPO_URL"
fi

if [[ -n "$SCRIPTS_DIR" ]]; then
  case ":$PATH:" in
    *":$SCRIPTS_DIR:"*) ;;
    *)
      echo ""
      echo "Note: add SuperContext's script directory to PATH if supercontext-init is not found:"
      echo "  export PATH=\"$SCRIPTS_DIR:\$PATH\""
      ;;
  esac
fi

echo ""
echo "Installing global SuperContext MCP skills..."
"$INSTALL_PYTHON" -P -m source.scripts.install_mcp_skills --scope global --agent "$TARGET_AGENT"

echo ""
echo "Registering local SuperContext MCP endpoint with host agents..."
"$INSTALL_PYTHON" -P -m source.scripts.register_mcp --agent "$TARGET_AGENT" --on-error warn

echo ""
echo "Done."
echo ""
echo "Next, in each repo you want indexed:"
echo "  supercontext-init"
echo ""
echo "For an active local MCP server in that repo:"
echo "  supercontext-init --serve"
