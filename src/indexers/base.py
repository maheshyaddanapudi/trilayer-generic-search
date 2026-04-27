from __future__ import annotations

from abc import ABC, abstractmethod

from src.models.core import MetadataChunk, SearchResult


class IndexWriter(ABC):
    @abstractmethod
    def index(self, chunks: list[MetadataChunk]) -> int:
        """Index chunks; return count of chunks indexed."""
        ...

    @property
    @abstractmethod
    def is_ready(self) -> bool: ...
