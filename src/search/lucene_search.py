from __future__ import annotations

from src.indexers.lucene import LuceneIndexWriter
from src.models.core import ParsedIntent, SearchResult


class LuceneSearch:
    def __init__(self, writer: LuceneIndexWriter) -> None:
        self._writer = writer

    def search(self, intent: ParsedIntent, top_k: int = 10,
               domain_id: str | None = None) -> list[SearchResult]:
        query = intent.expanded_query or ""
        if not query:
            return []
        return self._writer.keyword_search(query, top_k, domain_id=domain_id)
