#!/usr/bin/env sh
# One-step installer for memory-bank
# Usage: bash install.sh
# Or pipe-install: curl -fsSL https://raw.githubusercontent.com/jdelgadoperez/memory-bank/main/install.sh | sh

set -e

REPO_URL="https://github.com/jdelgadoperez/memory-bank"
INSTALL_DIR="${MEMORY_BANK_DIR:-$HOME/.local/share/memory-bank}"

# ── 1. Clone or update ────────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "→ Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "→ Cloning memory-bank to $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 2. Install dependencies ───────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it first: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

echo "→ Installing with uv"
uv sync --extra mcp

# Use 'uv run' so commands execute inside the project venv without activation
MB="uv run memory-bank"

# ── 3. Wire Claude Code integration ──────────────────────────────────────────
echo "→ Installing Claude Code hooks, skills, and MCP server"
$MB setup install --on recommended

# ── 4. Initial ingest ─────────────────────────────────────────────────────────
echo "→ Ingesting existing Claude Code history"
$MB ingest claude-code

echo ""
echo "✓ memory-bank is ready!"
echo ""
echo "  uv run memory-bank search \"your query\"   # search chat history"
echo "  uv run memory-bank ui                    # open browser UI"
echo "  uv run memory-bank stats                 # see what's indexed"
echo ""
echo "  Tip: add an alias to your shell profile for convenience:"
echo "    alias memory-bank=\"$INSTALL_DIR/.venv/bin/memory-bank\""
