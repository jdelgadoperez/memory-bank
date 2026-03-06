"""Abstract base class for all ingestors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from ..schema import ChatMessage


class BaseIngestor(ABC):
    """
    Implement this to add a new data source.

    Subclasses only need to implement `iter_messages()` which yields
    ChatMessage objects. The CLI and DB layer handle batching and upsert.
    """

    source_name: str = "unknown"

    @abstractmethod
    def iter_messages(self) -> Iterator[ChatMessage]:
        """Yield ChatMessage objects from the data source."""
        ...

    def validate(self) -> list[str]:
        """
        Optional pre-flight checks. Return a list of human-readable error strings.
        An empty list means all checks passed.
        """
        return []
