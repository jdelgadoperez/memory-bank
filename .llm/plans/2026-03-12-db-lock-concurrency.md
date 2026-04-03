# DB Lock Concurrency Plan

## Problem

Qdrant embedded mode takes an exclusive file lock on the storage directory. The UI server holds a `MemoryDB` instance (and therefore the lock) for its entire lifetime. This blocks all CLI commands (`ingest`, `search`, `stats`) and the background session hook while the UI is running.

## Root Cause

`MemoryDB.__init__` calls `QdrantClient(path=...)` which immediately acquires the lock. The UI creates one instance at startup and never releases it.

## Design Decisions

- **No Docker / Qdrant server mode** — disproportionate infrastructure for a single-user local tool
- **No API forwarding** — couples CLI to UI server, inverts dependency hierarchy
- **Per-request lock acquisition** — UI holds the lock only during active requests, not during idle time
- **Separate embedder from client** — fastembed model loads once (slow), Qdrant client opens/closes per operation (fast)
- **Pending marker fallback** — safety valve for the rare case where two processes collide

## Implementation

### 1. Restructure `MemoryDB` — separate embedder from Qdrant client (`db.py`)

Currently `MemoryDB.__init__` does three things:
1. Loads/caches the fastembed model (slow, ~seconds first time)
2. Opens the Qdrant client (acquires exclusive lock)
3. Ensures collections and indexes exist

**New design:**
- The embedder stays on the instance, loaded once in `__init__` (or lazily on first use, as it already does)
- The Qdrant client is NOT opened in `__init__`
- Instead, add a context manager pattern for acquiring/releasing the client:

```python
class MemoryDB:
    def __init__(self, path=None):
        self.path = path or get_db_path()
        self.path.mkdir(parents=True, exist_ok=True)
        self._embedder = None
        self._embedder_loaded = False
        self._client = None

    @contextmanager
    def _connect(self):
        """Acquire the Qdrant client for the duration of an operation."""
        client = QdrantClient(path=str(self.path))
        self._client = client
        try:
            self._ensure_collections()
            yield client
        finally:
            self._client = None
            client.close()
```

- All public methods (`upsert`, `search`, `list_sessions`, etc.) wrap their Qdrant calls in `with self._connect():`
- The embedder (`_embed`) does NOT need the client — it runs independently
- This means: embed first (no lock needed), then connect briefly to write/read

**Method flow example (upsert):**
1. Filter out existing IDs — needs client briefly
2. Embed new texts — no client needed
3. Write points — needs client briefly

Since embedding is the slow part and doesn't need the lock, the lock is held for milliseconds during the actual Qdrant I/O.

**Optimization:** For batch operations (like ingest writing hundreds of messages), hold the client open for the entire batch rather than per-message. The lock window is still short (seconds, not hours).

### 2. Update UI server to use per-request MemoryDB (`cli.py`)

The UI server's `Handler.do_GET` currently references `memory_db` (captured in closure). With the new design, this just works — each API call's `search`/`list_sessions`/etc. acquires and releases the lock within the method call. No changes needed to the handler itself, only to `MemoryDB`.

The `memory_db` instance stays alive for the server's lifetime (holding the loaded embedder in memory), but the Qdrant lock is only held during active requests.

### 3. Graceful lock failure handling (`db.py`)

Wrap the `QdrantClient` construction in a try/except that catches `portalocker.exceptions.AlreadyLocked` and `RuntimeError` (the Qdrant wrapper). Raise a custom `DatabaseLockedError` with an actionable message.

### 4. Pending marker fallback for ingest (`cli.py`)

When `_run_ingest` encounters a `DatabaseLockedError`:
1. Write a marker file to `~/.memory-bank/pending/<source>` (e.g., `claude-code`)
2. Log a message: "DB is locked. Ingest queued — will run on next invocation."
3. Exit cleanly (not a crash)

When `_run_ingest` succeeds and the lock is available:
1. After completing the requested ingest, check `~/.memory-bank/pending/`
2. If marker files exist, drain them by running the corresponding ingestors
3. Remove marker files after successful processing

This means the hook can always exit quickly. The pending work gets picked up by the next successful ingest, whether that's the hook firing again or a manual CLI invocation.

### 5. Better error messages for interactive CLI (`cli.py`)

For interactive commands (`search`, `stats`), catch `DatabaseLockedError` and print:
```
Error: Database is locked by another process.
If the UI server is running, stop it with Ctrl+C, or use the UI's built-in search.
```

## Implementation Order

1. Add `DatabaseLockedError` exception class to `db.py`
2. Refactor `MemoryDB` to separate embedder from client with `_connect()` context manager
3. Update all public methods to use `_connect()`
4. Add pending marker logic to `_run_ingest` in `cli.py`
5. Add friendly error messages for interactive CLI commands
6. Test: run UI and CLI concurrently

## Testing Strategy

- Start UI server, run `memory-bank ingest claude-code` — should succeed (lock released between UI requests)
- Start UI server, run `memory-bank stats` — should succeed
- Start UI server, run `memory-bank search "test"` — should succeed
- Simulate lock collision: verify pending marker is created and drained on next run
- Verify UI still works normally after refactor
- Verify ingest still works with session accumulation

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Per-request open/close adds latency | At 3000 records on local disk, Qdrant open/close is ~50ms. Imperceptible. |
| Two processes connect at the exact same instant | Pending marker fallback handles this gracefully |
| `_ensure_collections` called on every connect | Qdrant's create_collection is idempotent. The index warnings are already suppressed. Could cache a "collections verified" flag on the instance after first connect. |
| Embedder memory stays allocated while UI is idle | Acceptable — it's ~100MB. The alternative (reloading per request) would add seconds of latency. |
