"""Tests for the recall hook command string — ensures stdout is not suppressed."""
from __future__ import annotations

from memory_bank.commands._recall_guard import RECALL_HOOK_COMMAND


class TestRecallHookCommand:
    def test_stderr_only_redirect(self):
        """Recall hook must only redirect stderr, not stdout.

        stdout carries the injected context that Claude reads. Redirecting it
        to the log file (2>&1) would silently swallow all recall output.
        """
        assert "2>>" in RECALL_HOOK_COMMAND, "stderr should be redirected to log"
        assert "2>&1" not in RECALL_HOOK_COMMAND, "stdout must NOT be merged into stderr redirect"

    def test_stdout_not_redirected(self):
        """The command must not contain a bare >> that would redirect stdout."""
        # Allow 2>> but not a bare >> (stdout redirect)
        import re
        bare_stdout_redirect = re.search(r"(?<!2)>>", RECALL_HOOK_COMMAND)
        assert bare_stdout_redirect is None, (
            f"RECALL_HOOK_COMMAND redirects stdout: {RECALL_HOOK_COMMAND!r}"
        )

    def test_command_invokes_recall_subcommand(self):
        """The hook command must call 'memory-bank hooks recall'."""
        assert "memory-bank hooks recall" in RECALL_HOOK_COMMAND
