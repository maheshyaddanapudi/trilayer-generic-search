from __future__ import annotations

from src.indexers.vector import VectorIndexWriter
from src.models.core import ParsedIntent, SearchResult


class VectorSearch:
    def __init__(self, writer: VectorIndexWriter, model) -> None:
        self._writer = writer
        self._model = model

    def search(self, intent: ParsedIntent, top_k: int = 10,
               domain_id: str | None = None) -> list[SearchResult]:
        query = intent.expanded_query or ""
        if not query:
            return []
        vec = self._model.encode([query], normalize_embeddings=True)[0].tolist()
        return self._writer.similarity_search(vec, top_k, domain_id=domain_id)
