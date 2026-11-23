"""Tests for copying data between embedded and server Qdrant (`memory-bank migrate`)."""
from __future__ import annotations

import random
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
from memory_bank.db import COLLECTION, VECTOR_SIZE, copy_collection, ensure_collection


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
        assert "Copied 40 points" in result.output
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
        assert "would copy 10 points" in result.output
        s = QdrantClient(path=str(fake_server))
        assert not s.collection_exists(COLLECTION)
        s.close()

    def test_unreachable_server_errors_without_docker(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QDRANT_URL", raising=False)
        with patch("memory_bank.db._ping_qdrant", return_value=False), patch(
            "memory_bank.db._docker_daemon_running", return_value=False
        ):
            result = self._run("--to", "server", "--db", str(tmp_path / "qdrant"))
        assert result.exit_code != 0
        assert "No Qdrant server is reachable" in result.output

    def test_to_embedded_never_autostarts_docker(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QDRANT_URL", raising=False)
        with patch("memory_bank.db._ping_qdrant", return_value=False), patch(
            "memory_bank.db._docker_daemon_running", return_value=True
        ), patch("memory_bank.db._ensure_qdrant_container") as start:
            result = self._run("--to", "embedded", "--db", str(tmp_path / "qdrant"))
        assert result.exit_code != 0
        start.assert_not_called()
