"""Tests for soft delete and auto-purge functionality."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from memory_bank.db import MemoryDB
from memory_bank.schema import ChatMessage


def _make_message(content: str = "hello", session_id: str | None = None) -> ChatMessage:
    sid = session_id or str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    return ChatMessage(
        id=ChatMessage.make_id("test", sid, "user", content, ts),
        source="test",
        session_id=sid,
        project="test-project",
        role="user",
        content=content,
        timestamp=ts,
    )


class TestSoftDelete:
    def test_delete_by_source_soft_sets_payload(self):
        """Soft delete sets is_deleted=True in the payload instead of removing the point."""
        msg = _make_message()
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = (
            [MagicMock(id=1, payload={"id": msg.id, "source": "test", "timestamp": msg.timestamp})],
            None,
        )

        db = MemoryDB.__new__(MemoryDB)
        db._url = None
        db._embedder = None
        db._embedder_loaded = True
        db._collections_verified = True

        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            db.delete_by_source("test", hard=False)

        mock_client.set_payload.assert_called_once()
        call_kwargs = mock_client.set_payload.call_args
        payload = call_kwargs[1]["payload"] if call_kwargs[1] else call_kwargs[0][1]
        assert payload["is_deleted"] is True
        assert "deleted_at" in payload

    def test_delete_by_source_hard_removes_points(self):
        """Hard delete still removes points from Qdrant."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        db = MemoryDB.__new__(MemoryDB)
        db._url = None
        db._embedder = None
        db._embedder_loaded = True
        db._collections_verified = True

        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            db.delete_by_source("test", hard=True)

        mock_client.delete.assert_called_once()

    def test_build_filter_excludes_soft_deleted(self):
        """_build_filter always adds must_not to exclude is_deleted=True points."""
        from qdrant_client.models import FieldCondition, MatchValue

        db = MemoryDB.__new__(MemoryDB)
        db._url = None
        db._embedder = None
        db._embedder_loaded = True
        db._collections_verified = True

        flt = db._build_filter(source="claude-code")

        assert flt is not None
        assert flt.must_not is not None
        deleted_condition = FieldCondition(key="is_deleted", match=MatchValue(value=True))
        assert any(
            c == deleted_condition for c in flt.must_not
        ), "Filter must exclude is_deleted=True points"

    def test_purge_expired_hard_deletes_old_soft_deleted(self):
        """purge_expired hard-deletes points soft-deleted more than 90 days ago."""
        old_ts = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.scroll.return_value = (
            [
                MagicMock(id=1, payload={"is_deleted": True, "deleted_at": old_ts}),
                MagicMock(id=2, payload={"is_deleted": True, "deleted_at": recent_ts}),
            ],
            None,
        )

        db = MemoryDB.__new__(MemoryDB)
        db._url = None
        db._embedder = None
        db._embedder_loaded = True
        db._collections_verified = True

        with patch.object(db, "_connect") as mock_connect:
            mock_connect.return_value.__enter__ = lambda s: mock_client
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            count = db.purge_expired(days=90)

        assert count == 1
        mock_client.delete.assert_called_once()
        deleted_ids = mock_client.delete.call_args[1]["points_selector"]
        assert deleted_ids == [1]
