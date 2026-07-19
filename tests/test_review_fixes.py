"""Regression tests for the feature-review fixes.

Each test pins a specific bug the review surfaced so it can't silently return.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from memory_bank.cli import cli
from memory_bank.commands.hooks import (
    PRECOMPACT_HOOK_COMMAND,
    PRECOMPACT_HOOK_MARKER,
    STOP_HOOK_MARKER,
)


def runner():
    return CliRunner()


class TestPreCompactHookCommand:
    """The redirect + backgrounding must not be swallowed by the `#` marker."""

    def test_redirect_and_background_precede_comment(self):
        cmd = PRECOMPACT_HOOK_COMMAND
        # The bug was `# precompact` appearing before `>>`, commenting out the
        # redirect and the `&`. Both must come before any comment.
        assert ">>" in cmd and "&" in cmd
        assert cmd.index(">>") < cmd.index("#")
        assert cmd.index("&") < cmd.index("#")

    def test_logs_to_ingest_log(self):
        assert ">> ~/.memory-bank/ingest.log 2>&1 &" in PRECOMPACT_HOOK_COMMAND

    def test_marker_independent_from_stop_hook(self):
        # Stop and PreCompact both run `ingest claude-code`; their markers must
        # not match each other or install/uninstall will collide.
        assert PRECOMPACT_HOOK_MARKER in PRECOMPACT_HOOK_COMMAND
        assert STOP_HOOK_MARKER not in PRECOMPACT_HOOK_COMMAND


class TestHooksInstallUpgradesStaleCommand:
    def test_stale_precompact_command_is_upgraded(self, tmp_path):
        settings = tmp_path / "settings.json"
        stale = "memory-bank ingest claude-code  # precompact >> ~/.memory-bank/ingest.log 2>&1 &"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreCompact": [
                            {"matcher": "", "hooks": [{"type": "command", "command": stale}]}
                        ]
                    }
                }
            )
        )

        result = runner().invoke(
            cli, ["hooks", "install", "--on", "precompact", "--settings", str(settings)]
        )
        assert result.exit_code == 0

        data = json.loads(settings.read_text())
        commands = [h["command"] for entry in data["hooks"]["PreCompact"] for h in entry["hooks"]]
        assert PRECOMPACT_HOOK_COMMAND in commands
        assert stale not in commands
        # Upgraded in place — not duplicated.
        assert len(commands) == 1


class TestDeleteSinceFootgunRemoved:
    def test_since_flag_rejected(self):
        result = runner().invoke(cli, ["delete", "--since", "7d"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_before_flag_still_documented(self):
        result = runner().invoke(cli, ["delete", "--help"])
        assert "--before" in result.output
        assert "--since" not in result.output


class TestStatsJson:
    @patch("memory_bank.db.MemoryDB")
    def test_stats_json_is_parseable(self, mock_db_cls):
        instance = MagicMock()
        instance._url = None
        instance.stats.return_value = {
            "total_messages": 42,
            "by_source": {"claude-code": 42},
            "db_path": "/tmp/x",
            "collection": "chat_history",
            "embedding_model": "neural",
        }
        mock_db_cls.return_value = instance

        result = runner().invoke(cli, ["stats", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["total_messages"] == 42
        assert payload["mode"] == "embedded"
