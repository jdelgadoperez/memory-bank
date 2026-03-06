#!/bin/bash
set -euo pipefail

echo '{"async": true, "asyncTimeout": 300000}'

# Install memory-bank and dependencies in editable mode
pip install -e /home/user/memory-bank --quiet

# Install the Claude Code skill symlink if not already done
SKILL_DIR="${HOME}/.claude/skills/memory-search"
SKILL_SRC="/home/user/memory-bank/skills/memory-search"

if [ ! -e "${SKILL_DIR}" ]; then
    ln -s "${SKILL_SRC}" "${SKILL_DIR}"
    echo "Installed memory-search skill -> ${SKILL_DIR}"
fi
