"""Tests for copying data between embedded and server Qdrant (`memory-bank migrate`)."""
from __future__ import annotations

import random
import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from memory_bank.cli import cli
from memory_bank.db import (
    COLLECTION,
    DEFAULT_INDEXING_THRESHOLD,
    VECTOR_SIZE,
    DatabaseLockedError,
    EmbeddedReader,
    copy_collection,
    copy_points,
    ensure_collection,
)


def _seed(client: QdrantClient, n: int, **payload) -> list[str]:
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )
    ids = [str(uuid.uuid4()) for _ in range(n)]
    client.upsert(
        COLLECTION,
        points=[
            PointStruct(
                id=pid,
                vector=[random.random() for _ in range(VECTOR_SIZE)],
                payload={"i": i, "source": "claude-code", **payload},
            )
            for i, pid in enumerate(ids)
        ],
    )
    return ids


@pytest.fixture
def clients(tmp_path):
    src = QdrantClient(path=str(tmp_path / "src"))
    dst = QdrantClient(path=str(tmp_path / "dst"))
    yield src, dst
    src.close()
    dst.close()


class TestCopyCollection:
    def test_copies_all_points_with_vectors_and_payloads(self, clients):
        src, dst = clients
        ids = _seed(src, 600, is_deleted=False)
        _seed(src, 5, is_deleted=True)

        batches: list[int] = []
        copied = copy_collection(src, dst, dst_is_server=False, batch_size=256, on_batch=batches.append)

        assert copied == 605
        assert sum(batches) == 605 and len(batches) == 3
        assert dst.count(COLLECTION, exact=True).count == 605

        a = src.retrieve(COLLECTION, ids=[ids[0]], with_vectors=True)[0]
        b = dst.retrieve(COLLECTION, ids=[ids[0]], with_vectors=True)[0]
        assert b.payload == a.payload
        assert b.vector == pytest.approx(a.vector)
        # Soft-deleted points stay soft-deleted.
        deleted = dst.count(
            COLLECTION,
            count_filter=Filter(must=[FieldCondition(key="is_deleted", match=MatchValue(value=True))]),
            exact=True,
        ).count
        assert deleted == 5

    def test_rerun_is_idempotent(self, clients):
        src, dst = clients
        _seed(src, 50)
        copy_collection(src, dst, dst_is_server=False)
        copy_collection(src, dst, dst_is_server=False)
        assert dst.count(COLLECTION, exact=True).count == 50

    def test_merges_into_existing_destination(self, clients):
        src, dst = clients
        _seed(src, 30)
        _seed(dst, 20)
        copy_collection(src, dst, dst_is_server=False)
        assert dst.count(COLLECTION, exact=True).count == 50

    def test_empty_source_copies_nothing(self, clients):
        src, dst = clients
        ensure_collection(src, server=False)
        assert copy_collection(src, dst, dst_is_server=False) == 0
        assert dst.collection_exists(COLLECTION)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(output: str) -> str:
    """CLI output without ANSI colour codes, panel borders or line wrapping."""
    return " ".join(_ANSI.sub("", output).replace("│", " ").split())


def _make_store(path, n: int, **payload) -> list[str]:
    c = QdrantClient(path=str(path))
    ids = _seed(c, n, **payload)
    c.close()
    return ids


def _server_stub(threshold):
    """A destination that looks like a server collection with *threshold*."""
    dst = MagicMock()
    dst.get_collections.return_value = MagicMock(collections=[MagicMock()])
    dst.get_collections.return_value.collections[0].name = COLLECTION
    dst.get_collection.return_value.config.optimizer_config.indexing_threshold = threshold
    return dst


def _thresholds(dst) -> list[int]:
    return [
        c.kwargs["optimizers_config"].indexing_threshold
        for c in dst.update_collection.call_args_list
    ]


class TestEmbeddedReader:
    def test_streams_every_point_with_vectors_and_payloads(self, tmp_path):
        ids = _make_store(tmp_path, 600, is_deleted=False)
        with EmbeddedReader(tmp_path) as r:
            assert r.count() == 600
            batches = list(r.batches(256))
        assert [len(b) for b in batches] == [256, 256, 88]
        got = {p.id: p for b in batches for p in b}
        assert set(got) == set(ids)

        c = QdrantClient(path=str(tmp_path))
        ref = c.retrieve(COLLECTION, ids=[ids[0]], with_vectors=True)[0]
        c.close()
        assert got[ids[0]].payload == ref.payload
        assert got[ids[0]].vector == pytest.approx(ref.vector)

    def test_newest_duplicate_row_wins(self, tmp_path):
        import pickle
        import sqlite3

        ids = _make_store(tmp_path, 3)
        db = tmp_path / "collection" / COLLECTION / "storage.sqlite"
        conn = sqlite3.connect(db)
        (blob,) = conn.execute("SELECT point FROM points LIMIT 1").fetchone()
        point = pickle.loads(blob)
        newer = PointStruct(id=point.id, vector=point.vector, payload={"marker": "newest"})
        # An older qdrant-client could leave a second row for the same point under another key.
        conn.execute("INSERT INTO points (id, point) VALUES (?, ?)", ("legacy-key", pickle.dumps(newer)))
        conn.commit()
        conn.close()

        with EmbeddedReader(tmp_path) as r:
            points = [p for b in r.batches() for p in b]
        assert len(points) == 3 and {p.id for p in points} == set(ids)
        assert next(p for p in points if p.id == point.id).payload == {"marker": "newest"}

    def test_missing_store_is_empty(self, tmp_path):
        with EmbeddedReader(tmp_path / "nothing-here") as r:
            assert r.count() == 0
            assert list(r.batches()) == []

    def test_refuses_store_held_by_another_client(self, tmp_path):
        _make_store(tmp_path, 1)
        holder = QdrantClient(path=str(tmp_path))
        try:
            with pytest.raises(DatabaseLockedError), EmbeddedReader(tmp_path):
                pass
        finally:
            holder.close()

    def test_holds_the_lock_while_open(self, tmp_path):
        _make_store(tmp_path, 1)
        with EmbeddedReader(tmp_path), pytest.raises(RuntimeError, match="already accessed"):
            QdrantClient(path=str(tmp_path))
        QdrantClient(path=str(tmp_path)).close()  # released afterwards


class TestCopyPointsToServer:
    def _batches(self, n_batches=2):
        return ([PointStruct(id=i, vector=[0.0] * 4, payload={})] for i in range(n_batches))

    def test_pauses_indexing_during_upload_and_restores_it(self):
        dst = _server_stub(threshold=20_000)
        copied = copy_points(self._batches(), dst, dst_is_server=True)
        assert copied == 2
        assert _thresholds(dst) == [0, 20_000]
        # Indexing went off before the first upsert and back on after the last.
        names = [c[0] for c in dst.method_calls if c[0] in ("update_collection", "upsert")]
        assert names == ["update_collection", "upsert", "upsert", "update_collection"]
        assert all(c.kwargs["wait"] is True for c in dst.upsert.call_args_list)

    def test_restores_indexing_when_upload_fails(self):
        dst = _server_stub(threshold=20_000)
        dst.upsert.side_effect = KeyboardInterrupt
        with pytest.raises(KeyboardInterrupt):
            copy_points(self._batches(), dst, dst_is_server=True)
        assert _thresholds(dst) == [0, 20_000]

    def test_threshold_left_at_zero_by_a_killed_run_is_reset_to_default(self):
        dst = _server_stub(threshold=0)
        copy_points(self._batches(), dst, dst_is_server=True)
        assert _thresholds(dst) == [0, DEFAULT_INDEXING_THRESHOLD]

    def test_embedded_destination_leaves_indexing_alone(self):
        dst = _server_stub(threshold=20_000)
        copy_points(self._batches(), dst, dst_is_server=False)
        dst.update_collection.assert_not_called()

    def test_pause_sleeps_between_batches(self):
        dst = _server_stub(threshold=20_000)
        with patch("memory_bank.db.time.sleep") as sleep:
            copy_points(self._batches(3), dst, dst_is_server=False, pause=0.25)
        assert [c.args[0] for c in sleep.call_args_list] == [0.25, 0.25, 0.25]


class TestEnsureCollection:
    def test_server_creates_payload_indexes(self):
        client = MagicMock()
        client.get_collections.return_value = MagicMock(collections=[])
        ensure_collection(client, server=True)
        client.create_collection.assert_called_once()
        fields = {c.kwargs["field_name"] for c in client.create_payload_index.call_args_list}
        assert fields == {"source", "project", "role", "session_id", "category"}

    def test_embedded_skips_payload_indexes(self):
        client = MagicMock()
        client.get_collections.return_value = MagicMock(collections=[])
        ensure_collection(client, server=False)
        client.create_payload_index.assert_not_called()


class TestMigrateCommand:
    def _run(self, *args):
        return CliRunner().invoke(cli, ["migrate", *args])

    def test_to_server_end_to_end(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QDRANT_URL", raising=False)
        emb = tmp_path / "qdrant"
        c = QdrantClient(path=str(emb))
        _seed(c, 40)
        c.close()

        # Stand in for the server with a second embedded store.
        fake_server = tmp_path / "server"
        with patch(
            "memory_bank.commands.migrate._open_server",
            side_effect=lambda *a, **k: QdrantClient(path=str(fake_server)),
        ):
            result = self._run("--to", "server", "--db", str(emb))

        assert result.exit_code == 0, result.output
        assert "Copied 40 points" in _plain(result.output)
        s = QdrantClient(path=str(fake_server))
        assert s.count(COLLECTION, exact=True).count == 40
        s.close()

    def test_dry_run_writes_nothing(self, tmp_path):
        emb = tmp_path / "qdrant"
        c = QdrantClient(path=str(emb))
        _seed(c, 10)
        c.close()

        fake_server = tmp_path / "server"
        with patch(
            "memory_bank.commands.migrate._open_server",
            side_effect=lambda *a, **k: QdrantClient(path=str(fake_server)),
        ):
            result = self._run("--to", "server", "--db", str(emb), "--dry-run")

        assert result.exit_code == 0, result.output
        assert "would copy 10 points" in _plain(result.output)
        s = QdrantClient(path=str(fake_server))
        assert not s.collection_exists(COLLECTION)
        s.close()

    def test_locked_store_errors_before_contacting_server(self, tmp_path):
        emb = tmp_path / "qdrant"
        _make_store(emb, 1)
        holder = QdrantClient(path=str(emb))
        try:
            with patch("memory_bank.commands.migrate._open_server") as open_server:
                result = self._run("--to", "server", "--db", str(emb))
        finally:
            holder.close()
        assert result.exit_code != 0
        assert "in use by another process" in _plain(result.output)
        open_server.assert_not_called()

    def test_unreachable_server_errors_without_docker(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QDRANT_URL", raising=False)
        with patch("memory_bank.db._ping_qdrant", return_value=False), patch(
            "memory_bank.db._docker_daemon_running", return_value=False
        ):
            result = self._run("--to", "server", "--db", str(tmp_path / "qdrant"))
        assert result.exit_code != 0
        assert "No Qdrant server is reachable" in _plain(result.output)

    def test_to_embedded_never_autostarts_docker(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QDRANT_URL", raising=False)
        with patch("memory_bank.db._ping_qdrant", return_value=False), patch(
            "memory_bank.db._docker_daemon_running", return_value=True
        ), patch("memory_bank.db._ensure_qdrant_container") as start:
            result = self._run("--to", "embedded", "--db", str(tmp_path / "qdrant"))
        assert result.exit_code != 0
        start.assert_not_called()
