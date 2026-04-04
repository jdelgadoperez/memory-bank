"""Pure skip-guard logic for the UserPromptSubmit recall hook.

Kept in a separate module to avoid circular imports: hooks.py imports from
cli.py, which imports hooks.py as part of command registration.
"""
from __future__ import annotations

import re

RECALL_HOOK_COMMAND = (
    "memory-bank hooks recall"
    " 2>> ~/.memory-bank/ingest.log"
)
RECALL_HOOK_MARKER = "memory-bank hooks recall"
RECALL_MIN_SCORE = 0.65
RECALL_LIMIT = 3
RECALL_SNIPPET_LENGTH = 300

SKIP_RECALL_PATTERNS = (
    r"^\s*(yes|no|ok|okay|sure|go ahead|continue|proceed|thanks?|done)\s*$",
    r"^\s*(commit|push|run|execute|add|remove|delete)\s+this\s*$",
    r"^\s*(what about|and|also|but|however)\s",
)


def should_skip_recall(prompt: str) -> bool:
    """Return True if the prompt has no semantic signal worth searching for."""
    stripped = prompt.strip()
    if len(stripped) < 15:
        return True
    return any(re.match(p, stripped, re.IGNORECASE) for p in SKIP_RECALL_PATTERNS)
