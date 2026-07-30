"""Tests for session-scoped delete and distill --replace-raw.

The two risky behaviours covered here:
  1. delete_session must never touch another session, and must never delete
     the summary record it is meant to leave behind.
  2. distill --replace-raw must only delete raw messages after a summary has
     been durably written for that session.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory_bank.db import MemoryDB
from memory_bank.schema import ChatMessage

SUMMARY_ROLE = "summary"


def _bare_db() -> MemoryDB:
    db = MemoryDB.__new__(MemoryDB)
    db._url = None
    db._embedder = None
    db._embedder_loaded = True
    db._collections_verified = True
    return db


def _point(pid: int, session_id: str, role: str = "user") -> MagicMock:
    return MagicMock(id=pid, payload={"session_id": session_id, "role": role})


class TestDeleteSession:
    def test_hard_delete_removes_only_matching_session(self):
        """Points belonging to other sessions are never passed to client.delete."""
        target = "session-a"
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        # Qdrant filters server-side, so only target-session points come back.
        mock_client.scroll.return_value = ([_point(1, target), _point(2, target)], None)

        db = _bare_db()
        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            removed = db.delete_session(target, hard=True)

        assert removed == 2
        scroll_filter = mock_client.scroll.call_args.kwargs["scroll_filter"]
        conditions = [c for c in scroll_filter.must if getattr(c, "key", None) == "session_id"]
        assert conditions, "delete_session must filter on session_id"
        assert conditions[0].match.value == target

    def test_summary_role_is_excluded_from_deletion(self):
        """The distilled summary must survive a replace-raw delete."""
        target = "session-a"
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = ([_point(1, target)], None)

        db = _bare_db()
        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            db.delete_session(target, exclude_role=SUMMARY_ROLE, hard=True)

        scroll_filter = mock_client.scroll.call_args.kwargs["scroll_filter"]
        excluded = [
            c for c in (scroll_filter.must_not or []) if getattr(c, "key", None) == "role"
        ]
        assert excluded, "summary role must be excluded via must_not"
        assert excluded[0].match.value == SUMMARY_ROLE

    def test_soft_delete_sets_payload_and_does_not_remove(self):
        target = "session-a"
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = ([_point(1, target)], None)

        db = _bare_db()
        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            db.delete_session(target, hard=False)

        mock_client.delete.assert_not_called()
        mock_client.set_payload.assert_called_once()
        payload = mock_client.set_payload.call_args.kwargs["payload"]
        assert payload["is_deleted"] is True
        assert payload["deleted_at"]

    def test_soft_delete_skips_already_deleted_points(self):
        """Repeat soft-deletes must not reset deleted_at and restart the purge clock."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = ([_point(1, "session-a")], None)

        db = _bare_db()
        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            db.delete_session("session-a", hard=False)

        scroll_filter = mock_client.scroll.call_args.kwargs["scroll_filter"]
        excluded = [
            c for c in (scroll_filter.must_not or []) if getattr(c, "key", None) == "is_deleted"
        ]
        assert excluded, "soft delete must exclude already-deleted points"

    def test_no_matches_returns_zero_without_calling_delete(self):
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = ([], None)

        db = _bare_db()
        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            assert db.delete_session("nope", hard=True) == 0

        mock_client.delete.assert_not_called()


def _summary_role() -> str:
    from memory_bank.commands.distill import SUMMARY_ROLE

    return SUMMARY_ROLE


class TestDistillReplaceRaw:
    """CLI-level behaviour of distill --replace-raw."""

    def _run(self, args, sessions, summarize_side_effect=None):
        from click.testing import CliRunner

        from memory_bank.commands import distill as distill_mod

        db = MagicMock()
        db.list_sessions.return_value = sessions
        db.list_summarized_session_ids.return_value = set()
        db.get_session.return_value = [
            {"role": "assistant", "content": "did a thing"},
            {"role": "user", "content": "ask"},
        ]
        db.delete_session.return_value = 7

        with patch.object(distill_mod, "MemoryDB", return_value=db), patch.object(
            distill_mod,
            "_summarize",
            side_effect=summarize_side_effect or (lambda *a, **k: "- summary"),
        ), patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            result = CliRunner().invoke(distill_mod.distill, args)
        return result, db

    def _session(self, sid="s1", count=50, ts="2026-01-01T00:00:00+00:00"):
        return {
            "session_id": sid,
            "project": "p",
            "source": "claude-code",
            "last_ts": ts,
            "title": "t",
            "message_count": count,
        }

    def test_summary_is_written_before_raw_delete(self):
        """Ordering guarantee: a crash between the two must never lose data."""
        result, db = self._run(["--before", "90d", "--replace-raw"], [self._session()])
        assert result.exit_code == 0
        names = [c[0] for c in db.method_calls]
        assert "upsert" in names and "delete_session" in names
        assert names.index("upsert") < names.index("delete_session")

    def test_failed_summary_does_not_delete_raw(self):
        """If the API call raises, that session keeps its raw messages."""
        result, db = self._run(
            ["--before", "90d", "--replace-raw"],
            [self._session()],
            summarize_side_effect=RuntimeError("api down"),
        )
        assert result.exit_code == 0
        db.delete_session.assert_not_called()

    def test_delete_excludes_summary_role(self):
        result, db = self._run(["--before", "90d", "--replace-raw"], [self._session()])
        assert db.delete_session.call_args.kwargs["exclude_role"] == _summary_role()

    def test_no_delete_without_replace_raw_flag(self):
        result, db = self._run(["--before", "90d"], [self._session()])
        db.delete_session.assert_not_called()

    def test_hard_requires_replace_raw(self):
        result, _ = self._run(["--hard"], [self._session()])
        assert result.exit_code != 0
        assert "--replace-raw" in result.output

    def test_min_messages_filters_small_sessions(self):
        sessions = [self._session("big", 50), self._session("small", 3)]
        result, db = self._run(
            ["--before", "90d", "--replace-raw", "--min-messages", "10"], sessions
        )
        assert result.exit_code == 0
        assert db.delete_session.call_count == 1
        assert db.delete_session.call_args.args[0] == "big"

    def test_limit_batches_oldest_first(self):
        sessions = [
            self._session("newer", 50, "2026-06-01T00:00:00+00:00"),
            self._session("older", 50, "2026-01-01T00:00:00+00:00"),
        ]
        result, db = self._run(["--before", "90d", "--limit", "1"], sessions)
        assert result.exit_code == 0
        assert db.upsert.call_count == 1
        assert db.get_session.call_args.args[0] == "older"

    def test_dry_run_writes_nothing(self):
        result, db = self._run(
            ["--before", "90d", "--replace-raw", "--hard", "--dry-run"], [self._session()]
        )
        assert result.exit_code == 0
        db.upsert.assert_not_called()
        db.delete_session.assert_not_called()
