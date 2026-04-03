"""Tests for the `memory-bank hooks recall` subcommand."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from memory_bank.cli import cli


def runner():
    return CliRunner()


class TestRecallDisabledByEnvVar:
    def test_disabled_by_env_var(self):
        result = runner().invoke(cli, ["hooks", "recall"], env={
            "MEMORY_BANK_RECALL": "0",
            "CLAUDE_USER_PROMPT": "How does auth work?",
        })
        assert result.exit_code == 0
        assert result.output == ""


class TestRecallNoPrompt:
    def test_no_prompt_env_var(self):
        result = runner().invoke(cli, ["hooks", "recall"], env={})
        assert result.exit_code == 0
        assert result.output == ""

    def test_empty_prompt(self):
        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "",
        })
        assert result.exit_code == 0
        assert result.output == ""


class TestRecallSkipGuard:
    def test_short_prompt_skipped(self):
        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "yes",
        })
        assert result.exit_code == 0
        assert result.output == ""

    def test_imperative_skipped(self):
        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "commit this",
        })
        assert result.exit_code == 0
        assert result.output == ""


class TestRecallOutput:
    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_formats_results_as_markdown(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = [
            {
                "score": 0.85,
                "timestamp": "2026-03-28T10:00:00+00:00",
                "role": "assistant",
                "project": "my-app",
                "session_id": "abc123def456ghij",
                "content": "The auth token refresh was failing because the middleware checked expiry.",
            },
            {
                "score": 0.75,
                "timestamp": "2026-03-25T14:00:00+00:00",
                "role": "user",
                "project": "my-app",
                "session_id": "xyz789uvw012stuv",
                "content": "We decided to use Redis for session storage.",
            },
        ]
        mock_subprocess.return_value = MagicMock(
            stdout="/Users/test/projects/my-app\n",
            returncode=0,
        )

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does the authentication middleware handle token refresh?",
        })

        assert result.exit_code == 0
        assert "<!-- memory-bank:recall -->" in result.output
        assert "<!-- /memory-bank:recall -->" in result.output
        assert "do not repeat it back to the user" in result.output
        assert "2026-03-28" in result.output
        assert "abc123def456ghij"[:16] in result.output
        assert "(assistant)" in result.output
        assert "auth token refresh" in result.output

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_no_output_when_no_results(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = []
        mock_subprocess.return_value = MagicMock(stdout="/tmp/proj\n", returncode=0)

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "Tell me about the quantum flux capacitor integration",
        })
        assert result.exit_code == 0
        assert result.output == ""

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_filters_below_min_score(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = [
            {"score": 0.50, "timestamp": "2026-03-28T10:00:00+00:00",
             "role": "assistant", "project": "x", "session_id": "s1",
             "content": "Low relevance result"},
        ]
        mock_subprocess.return_value = MagicMock(stdout="/tmp/proj\n", returncode=0)

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does authentication work in this project?",
        })
        assert result.exit_code == 0
        assert result.output == ""

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_deduplicates_by_session(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = [
            {"score": 0.90, "timestamp": "2026-03-28T10:00:00+00:00",
             "role": "assistant", "project": "x", "session_id": "same-session",
             "content": "First chunk from same session"},
            {"score": 0.88, "timestamp": "2026-03-28T10:05:00+00:00",
             "role": "assistant", "project": "x", "session_id": "same-session",
             "content": "Second chunk from same session"},
            {"score": 0.80, "timestamp": "2026-03-25T14:00:00+00:00",
             "role": "user", "project": "x", "session_id": "different-session",
             "content": "Result from different session"},
        ]
        mock_subprocess.return_value = MagicMock(stdout="/tmp/proj\n", returncode=0)

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does the database connection pooling work?",
        })
        assert result.exit_code == 0
        assert "First chunk" in result.output
        assert "Second chunk" not in result.output
        assert "different session" in result.output

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_truncates_long_snippets(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        long_content = "A" * 500
        mock_db.search.return_value = [
            {"score": 0.85, "timestamp": "2026-03-28T10:00:00+00:00",
             "role": "assistant", "project": "x", "session_id": "s1",
             "content": long_content},
        ]
        mock_subprocess.return_value = MagicMock(stdout="/tmp/proj\n", returncode=0)

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does the authentication middleware handle token refresh?",
        })
        assert result.exit_code == 0
        assert "A" * 300 in result.output
        assert "A" * 301 not in result.output

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_omits_project_when_matches_current(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = [
            {"score": 0.85, "timestamp": "2026-03-28T10:00:00+00:00",
             "role": "assistant", "project": "my-app", "session_id": "s1",
             "content": "Some relevant content here"},
        ]
        mock_subprocess.return_value = MagicMock(
            stdout="/Users/test/projects/my-app\n", returncode=0,
        )

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does the authentication middleware handle token refresh?",
        })
        assert result.exit_code == 0
        assert "project:" not in result.output

    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_shows_project_when_different(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = [
            {"score": 0.85, "timestamp": "2026-03-28T10:00:00+00:00",
             "role": "assistant", "project": "other-app", "session_id": "s1",
             "content": "Some relevant content here"},
        ]
        mock_subprocess.return_value = MagicMock(
            stdout="/Users/test/projects/my-app\n", returncode=0,
        )

        result = runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": "How does the authentication middleware handle token refresh?",
        })
        assert result.exit_code == 0
        assert "project: other-app" in result.output


class TestRecallQueryPreprocessing:
    @patch("memory_bank.commands.hooks.MemoryDB")
    @patch("memory_bank.commands.hooks.subprocess.run")
    def test_truncates_query_to_512(self, mock_subprocess, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.search.return_value = []
        mock_subprocess.return_value = MagicMock(stdout="/tmp/proj\n", returncode=0)

        long_prompt = "A" * 1000
        runner().invoke(cli, ["hooks", "recall"], env={
            "CLAUDE_USER_PROMPT": long_prompt,
        })

        call_args = mock_db.search.call_args
        query_arg = call_args.kwargs.get("query") or call_args[1].get("query") or call_args[0][0]
        assert len(query_arg) == 512
