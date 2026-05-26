#!/usr/bin/env sh
# One-step installer for memory-bank
# Usage: bash install.sh
# Or pipe-install: curl -fsSL https://raw.githubusercontent.com/jdelgadoperez/memory-bank/main/install.sh | sh

set -e

BIN_DIR="$HOME/.local/bin"

# ── 1. Check for uv ───────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing uv first..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# ── 2. Install memory-bank ────────────────────────────────────────────────────
echo "→ Installing memory-bank"
uv tool install "git+https://github.com/jdelgadoperez/memory-bank.git"

# ── 3. Ensure ~/.local/bin is on PATH ─────────────────────────────────────────
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo ""
    echo "  ⚠ $BIN_DIR is not in your PATH."
    echo "  Add this to your shell profile (~/.zshrc or ~/.bashrc) and restart your terminal:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    export PATH="$BIN_DIR:$PATH"
    ;;
esac

# ── 4. Wire Claude Code integration ──────────────────────────────────────────
echo "→ Installing Claude Code hooks, skills, and MCP server"
memory-bank setup install --on recommended

# ── 5. Initial ingest ─────────────────────────────────────────────────────────
echo "→ Ingesting existing Claude Code history"
memory-bank ingest claude-code

echo ""
echo "✓ memory-bank is ready!"
echo ""
echo "  memory-bank search \"your query\"   # search chat history"
echo "  memory-bank ui                    # open browser UI"
echo "  memory-bank stats                 # see what's indexed"
