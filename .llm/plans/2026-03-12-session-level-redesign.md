# Session-Level Redesign Plan

## Objective

Redesign memory-bank from storing individual chat messages to tracking full conversations (sessions). The primary use case is semantic search via CLI/skills to catch up on past work. The UI is a secondary verification/browsing tool.

## Current State

- Single Qdrant collection `chat_history` with one point per message
- `ChatMessage` schema: id, source, session_id, project, role, content, timestamp, metadata
- No session-level awareness — messages are flat and disconnected
- UI only shows data after a search query (no browse view)
- No payload indexes — all filters are full scans

## Design Decisions

- **Dual-collection architecture**: `chat_history` (message-level semantic search) + `sessions` (session-level listing/search)
- **First user message as summary**: Use `slug` for title when available, first user message as embedding text
- **Unconditional session upserts**: Sessions grow over time, so always overwrite (not skip-if-exists)
- **Messages first, session second**: During ingest, write messages then session record to avoid phantom sessions
- **Sort in Python**: Qdrant scroll has no ordering — sort sessions by `last_timestamp` in application code

## Schema Changes

### New `Session` dataclass (`schema.py`)

```python
@dataclass
class Session:
    id: str              # deterministic hash from source + session_id
    source: str          # "claude-code" | "claude-desktop" | custom
    project: str         # decoded project name (leaf)
    title: str           # slug if available, else first user message
    summary: str         # text used for embedding (may differ from title)
    message_count: int
    first_timestamp: str # ISO 8601
    last_timestamp: str  # ISO 8601
    model: str           # primary model used in session
    metadata: dict       # git_branch, cwd, version, project_path

    @staticmethod
    def make_id(source: str, session_id: str) -> str:
        """Deterministic ID from source + session UUID."""
        ...

    def to_payload(self) -> dict[str, Any]:
        """Flat dict for Qdrant payload."""
        ...
```

### `ChatMessage` — no changes

Existing schema stays as-is. `session_id` field already provides the join key.

## DB Layer Changes (`db.py`)

### Collection setup

- `_ensure_collection` creates both `chat_history` and `sessions`
- Same vector config: 384-dim, COSINE, BAAI/bge-small-en-v1.5

### Payload indexes (added in `_ensure_collection`)

**`chat_history`:**
- `session_id` (keyword) — for session drill-in queries
- `source` (keyword) — for source filtering and stats
- `project` (keyword) — for project filtering
- `role` (keyword) — for role filtering

**`sessions`:**
- `source` (keyword)
- `project` (keyword)

### New methods

| Method | Description |
|---|---|
| `upsert_sessions(sessions: list[Session])` | Unconditional overwrite — no skip-if-exists check |
| `list_sessions(limit, source, project)` | Scroll `sessions`, sort by `last_timestamp` desc in Python |
| `get_session_messages(session_id, limit, offset)` | Scroll `chat_history` filtered by `session_id`, sort by timestamp. Default limit=200. |
| `search_sessions(query, limit, source, project)` | Semantic search against `sessions` collection |

### Modified methods

| Method | Change |
|---|---|
| `stats()` | Report session count. Use filtered `count()` per source instead of full scroll loop |
| `delete_by_source()` | Delete from both collections |

## Ingest Flow Changes

### Current flow
1. Ingestor yields `ChatMessage` objects one at a time
2. `_run_ingest` batches and upserts into `chat_history`

### New flow
1. Ingestor yields `ChatMessage` objects (unchanged interface)
2. `_run_ingest` batches and upserts messages into `chat_history` (unchanged)
3. **While iterating, accumulate session metadata** in a `dict[str, SessionAccumulator]` keyed by `session_id`:
   - Track first/last timestamp
   - Count messages
   - Capture first user message text (for summary)
   - Capture slug from metadata (for title)
   - Capture model from metadata
   - Capture git_branch, cwd, project_path
4. **After all messages processed**, build `Session` objects from the accumulator
5. Bulk upsert all sessions into `sessions` collection (unconditional overwrite)

This is a single pass over the source data. Memory overhead: one dict entry per session.

## UI Changes

### Navigation

- Two-tab navigation: **Sessions** (default) and **Search**
- Session detail is a contextual layer above Sessions (not a third tab)
- Use `history.pushState` for detail view so browser back button works
- Single `popstate` listener returns to session list — no full router needed
- Sidebar filters (source, project) persist across view changes in JS state
- Role filter only shown in search view (not relevant for session list/detail)

### Session list view (default on load)

- Table showing all sessions sorted by `last_timestamp` descending
- Columns: Project, Title, Date Range, Message Count, Model
- Clickable rows drill into session detail
- Filterable by source, project from sidebar
- Empty state: informative message with `memory-bank ingest claude-code` instructions

### Session detail view (drill-in from session list)

- Session metadata header: project, date range, model, git branch
- Full conversation thread in chronological order
- Layout: left-border role indicator (blue=user, green=assistant), max-width ~800px centered
- Tall assistant messages collapsed at 400px with "Show more" toggle
- `content-visibility: auto` on message elements for free performance
- Code blocks: `overflow-x: auto`, slightly different background
- Timestamps: right-aligned, muted, small
- Back button returns to session list

### Search view

- Message-level semantic search (existing behavior)
- Results include `session_point_id` for linking to full conversation context
- Cards and list view toggle stays
- Role filter visible in this view only

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/sessions` | List sessions. Params: `source`, `project`, `limit` (default 50). Sorted by `last_timestamp` desc. |
| `GET /api/sessions/<id>` | Session detail. Returns `{ session: {...}, messages: [...] }` envelope. Params: `limit` (default 200), `offset`. |
| `GET /api/search` | Message-level semantic search. Results include `session_point_id`. |
| `GET /api/stats` | Extended with session count. |

**Removed:** `/api/list` — superseded by session-based browsing.

**Error handling:** Consistent `{ "error": "..." }` shape with proper HTTP status codes (400, 404, 500).

## CLI Changes

Consider adding session-level commands (can defer to a follow-up):
- `memory-bank sessions list [--project P] [--source S] [--limit N]`
- `memory-bank sessions search QUERY [--limit N]`
- `memory-bank sessions show SESSION_ID`

## Implementation Order

1. **Schema**: Add `Session` dataclass to `schema.py`
2. **DB**: Add `sessions` collection, payload indexes, new methods to `db.py`
3. **Ingest**: Update `_run_ingest` in `cli.py` with session accumulation logic
4. **Re-ingest**: Run `memory-bank ingest claude-code` to populate `sessions` from existing data
5. **UI**: Rebuild with session list + detail view + search
6. **CLI commands**: Add session-level CLI commands (optional, can defer)

## Testing Strategy

- Verify idempotent re-ingest: run ingest twice, confirm no duplicates
- Verify session metadata accuracy: spot-check message counts, timestamps against raw JSONL
- Verify UI session list loads and drill-in shows correct conversation
- Verify search still works at message level
- Verify `stats` reports both message and session counts
- Verify `delete_by_source` cleans both collections
- Verify browser back button works from session detail

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| No cross-collection transactions in Qdrant | Write messages first, session second. Re-ingest fixes inconsistencies. |
| Session summary embedding quality varies | Use slug as title when available. Start with first user message for embedding, iterate later. |
| Scroll ordering not guaranteed | Sort in Python — acceptable at expected scale (hundreds to low thousands of sessions) |
| Same session ingested from different sources | Point ID encodes source + session_id, so they're separate records. Source column in UI makes this visible. |
