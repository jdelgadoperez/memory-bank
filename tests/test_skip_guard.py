"""Tests for the should_skip_recall skip guard."""
from __future__ import annotations

from memory_bank.commands._recall_guard import should_skip_recall


class TestShouldSkipRecall:
    """should_skip_recall returns True for prompts with no semantic signal."""

    def test_short_prompt_skipped(self):
        assert should_skip_recall("yes") is True

    def test_short_prompt_ok(self):
        assert should_skip_recall("ok") is True

    def test_short_prompt_no(self):
        assert should_skip_recall("no") is True

    def test_short_prompt_under_15_chars(self):
        assert should_skip_recall("do it now") is True

    def test_imperative_commit_this(self):
        assert should_skip_recall("commit this") is True

    def test_imperative_push_this(self):
        assert should_skip_recall("push this") is True

    def test_imperative_run_this(self):
        assert should_skip_recall("run this") is True

    def test_imperative_delete_this(self):
        assert should_skip_recall("delete this") is True

    def test_continuation_what_about(self):
        assert should_skip_recall("what about the other approach") is True

    def test_continuation_and(self):
        assert should_skip_recall("and also fix the tests") is True

    def test_continuation_but(self):
        assert should_skip_recall("but what if we used Redis instead") is True

    def test_thanks_skipped(self):
        assert should_skip_recall("thanks") is True

    def test_go_ahead_skipped(self):
        assert should_skip_recall("  go ahead  ") is True

    def test_proceed_skipped(self):
        assert should_skip_recall("proceed") is True

    def test_done_skipped(self):
        assert should_skip_recall("done") is True

    def test_real_question_not_skipped(self):
        assert should_skip_recall("How does the authentication middleware handle token refresh?") is False

    def test_search_intent_not_skipped(self):
        assert should_skip_recall("What was that Docker networking fix we did last week?") is False

    def test_technical_prompt_not_skipped(self):
        assert should_skip_recall("Refactor the database connection pooling to use async") is False

    def test_case_insensitive(self):
        assert should_skip_recall("YES") is True
        assert should_skip_recall("Go Ahead") is True
        assert should_skip_recall("COMMIT THIS") is True

    def test_whitespace_handling(self):
        assert should_skip_recall("   yes   ") is True
        assert should_skip_recall("\n  ok  \n") is True

    def test_empty_string(self):
        assert should_skip_recall("") is True
