#!/usr/bin/env sh
# One-step installer for memory-bank
# Usage: bash install.sh
# Or pipe-install: curl -fsSL https://raw.githubusercontent.com/jdelgadoperez/memory-bank/main/install.sh | sh

set -e

REPO_URL="https://github.com/jdelgadoperez/memory-bank"
INSTALL_DIR="${MEMORY_BANK_DIR:-$HOME/.local/share/memory-bank}"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/memory-bank"

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

# ── 3. Symlink binary so 'memory-bank' works from any shell ──────────────────
echo "→ Linking memory-bank to $BIN_PATH"
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/.venv/bin/memory-bank" "$BIN_PATH"

# Warn if ~/.local/bin is not on PATH
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo ""
    echo "  ⚠ $BIN_DIR is not in your PATH."
    echo "  Add this to your shell profile (~/.zshrc or ~/.bashrc) and restart your terminal:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    ;;
esac

# ── 4. Wire Claude Code integration ──────────────────────────────────────────
echo "→ Installing Claude Code hooks, skills, and MCP server"
"$BIN_PATH" setup install --on recommended

# ── 5. Initial ingest ─────────────────────────────────────────────────────────
echo "→ Ingesting existing Claude Code history"
"$BIN_PATH" ingest claude-code

echo ""
echo "✓ memory-bank is ready!"
echo ""
echo "  memory-bank search \"your query\"   # search chat history"
echo "  memory-bank ui                    # open browser UI"
echo "  memory-bank stats                 # see what's indexed"
