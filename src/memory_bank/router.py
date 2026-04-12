"""Route upsert calls to either direct MemoryDB or the UI server's HTTP API."""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path

from .schema import ChatMessage


class IngestRouter:
    """Base class for routing ingest upserts."""

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DirectRouter(IngestRouter):
    """Upserts directly to the local Qdrant DB."""

    def __init__(self, db_path: Path | None = None):
        from .db import MemoryDB

        self._db = MemoryDB(db_path)

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        return self._db.upsert(messages)


class HttpRouter(IngestRouter):
    """Upserts via the UI server's /api/ingest endpoint."""

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def upsert(self, messages: list[ChatMessage]) -> tuple[int, int]:
        payload = json.dumps({
            "messages": [m.to_payload() for m in messages],
        }).encode()

        request = urllib.request.Request(
            f"{self._base_url}/api/ingest",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read())
                return data["inserted"], data["skipped"]
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise RuntimeError(
                f"UI server ingest request failed: {exc}\n"
                "If the UI server crashed, re-run the ingest command."
            ) from exc


def resolve_router(db_path: Path | None = None) -> IngestRouter:
    """Return the appropriate router for ingest upserts.

    When a Qdrant server (Docker or external) is reachable, use DirectRouter so
    ingest connects to it directly. Multiple clients can safely share a Qdrant
    server, so there is no need to round-trip through the UI server.

    HttpRouter is only used when no Qdrant server is reachable (embedded mode)
    AND the UI server is running — in that case routing through the UI avoids
    embedded Qdrant file-lock contention between the two processes.
    """
    from .db import _ping_qdrant, QDRANT_DOCKER_URL

    # Qdrant server is available — connect directly, skip the UI server.
    if _ping_qdrant(QDRANT_DOCKER_URL):
        return DirectRouter(db_path=db_path)

    # Embedded mode: route through the UI server if it is running to avoid
    # holding the embedded Qdrant file lock in two processes simultaneously.
    ui_info = _detect_running_ui()
    if ui_info is not None:
        return HttpRouter(base_url=ui_info)

    return DirectRouter(db_path=db_path)


def _detect_running_ui() -> str | None:
    """Check if the UI server is running and reachable. Returns base URL or None."""
    import os

    pid_file = Path.home() / ".memory-bank" / "ui.pid"
    if not pid_file.exists():
        return None

    try:
        data = json.loads(pid_file.read_text())
        pid, port = data["pid"], data["port"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None

    # Check if process is alive
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # process exists but we can't signal it — still alive

    # Ping the server to confirm it's actually responding
    base_url = f"http://127.0.0.1:{port}"
    try:
        request = urllib.request.Request(f"{base_url}/api/stats", method="GET")
        with urllib.request.urlopen(request, timeout=2) as response:
            if response.status == 200:
                return base_url
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    return None
