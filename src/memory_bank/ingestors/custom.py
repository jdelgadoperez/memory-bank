"""
Generic ingestor for arbitrary data sources.

Usage — define a mapper function and pass it to CustomIngestor:

    from memory_bank.ingestors.custom import CustomIngestor, SourceRecord

    def my_mapper(record: dict) -> SourceRecord | None:
        if not record.get("body"):
            return None
        return SourceRecord(
            session_id=record["thread_id"],
            role="user" if record["author"] == "me" else "assistant",
            content=record["body"],
            timestamp=record["sent_at"],
            project=record.get("channel", ""),
            metadata={"platform": "slack"},
        )

    ingestor = CustomIngestor(
        source_name="slack",
        records=[...],          # list of raw dicts
        mapper=my_mapper,
    )

You can also provide a file_path to a JSON or JSONL file instead of raw records.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from ..schema import ChatMessage
from .base import BaseIngestor


@dataclass
class SourceRecord:
    """Intermediate struct returned by a mapper function."""
    session_id: str
    role: str                            # "user" | "assistant" | "system"
    content: str
    timestamp: str = ""
    project: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


MapperFn = Callable[[dict], "SourceRecord | None"]


class CustomIngestor(BaseIngestor):
    """
    Ingest any data source by providing:
      - source_name: unique string identifier (e.g. "slack", "notion", "discord")
      - records OR file_path: raw data to map
      - mapper: function that converts a raw dict to a SourceRecord (or None to skip)
    """

    def __init__(
        self,
        source_name: str,
        mapper: MapperFn,
        records: list[dict] | None = None,
        file_path: Path | str | None = None,
    ):
        self.source_name = source_name
        self._mapper = mapper
        self._records = records
        self._file_path = Path(file_path) if file_path else None

    def validate(self) -> list[str]:
        errors = []
        if self._records is None and self._file_path is None:
            errors.append("Either 'records' or 'file_path' must be provided.")
        if self._file_path and not self._file_path.exists():
            errors.append(f"File not found: {self._file_path}")
        return errors

    def iter_messages(self) -> Iterator[ChatMessage]:
        for raw in self._iter_raw():
            try:
                result = self._mapper(raw)
            except Exception as exc:
                continue
            if result is None:
                continue
            if not result.content.strip():
                continue
            msg_id = ChatMessage.make_id(
                self.source_name,
                result.session_id,
                result.role,
                result.content,
                result.timestamp,
            )
            yield ChatMessage(
                id=msg_id,
                source=self.source_name,
                session_id=result.session_id,
                project=result.project,
                role=result.role,
                content=result.content,
                timestamp=result.timestamp,
                metadata=result.metadata,
            )

    def _iter_raw(self) -> Iterator[dict]:
        if self._records is not None:
            yield from self._records
            return

        path = self._file_path
        suffix = path.suffix.lower()
        with open(path, encoding="utf-8") as fh:
            if suffix == ".jsonl":
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            pass
            else:
                data = json.load(fh)
                if isinstance(data, list):
                    yield from data
                elif isinstance(data, dict):
                    # Try common wrapper keys
                    for key in ("messages", "records", "items", "data", "conversations"):
                        if key in data and isinstance(data[key], list):
                            yield from data[key]
                            return
                    yield data
