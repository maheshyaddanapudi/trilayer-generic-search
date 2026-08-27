from __future__ import annotations

import logging
import shutil
from pathlib import Path

from whoosh import index as whoosh_index
from whoosh.fields import ID, TEXT, Schema
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.writing import AsyncWriter

from src.indexers.base import IndexWriter
from src.models.core import MetadataChunk, SearchResult

log = logging.getLogger(__name__)

_SCHEMA = Schema(
    chunk_id=ID(stored=True, unique=True),
    domain_id=ID(stored=True),
    entity_id=ID(stored=True),
    entity_type=ID(stored=True),
    breadcrumb=TEXT(stored=True),
)


class LuceneIndexWriter(IndexWriter):
    def __init__(self, index_dir: Path) -> None:
        self._base_dir = index_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._indices: dict[str, whoosh_index.FileIndex] = {}

    def _get_or_create(self, domain_id: str) -> whoosh_index.FileIndex:
        if domain_id not in self._indices:
            domain_dir = self._base_dir / domain_id
            domain_dir.mkdir(parents=True, exist_ok=True)
            if whoosh_index.exists_in(str(domain_dir)):
                ix = whoosh_index.open_dir(str(domain_dir))
            else:
                ix = whoosh_index.create_in(str(domain_dir), _SCHEMA)
            self._indices[domain_id] = ix
        return self._indices[domain_id]

    def index(self, chunks: list[MetadataChunk]) -> int:
        if not chunks:
            return 0
        by_domain: dict[str, list[MetadataChunk]] = {}
        for c in chunks:
            by_domain.setdefault(c.domain_id, []).append(c)

        total = 0
        for domain_id, domain_chunks in by_domain.items():
            ix = self._get_or_create(domain_id)
            writer = AsyncWriter(ix)
            for c in domain_chunks:
                writer.update_document(
                    chunk_id=c.chunk_id,
                    domain_id=c.domain_id,
                    entity_id=c.entity_id,
                    entity_type=c.entity_type,
                    breadcrumb=c.breadcrumb,
                )
            writer.commit()
            total += len(domain_chunks)
        return total

    def keyword_search(self, query_str: str, top_k: int,
                       domain_id: str | None = None) -> list[SearchResult]:
        if domain_id:
            domains = [domain_id] if domain_id in self._indices else []
            if not domains:
                # Try to open existing index on disk
                domain_dir = self._base_dir / domain_id
                if whoosh_index.exists_in(str(domain_dir)):
                    self._indices[domain_id] = whoosh_index.open_dir(str(domain_dir))
                    domains = [domain_id]
        else:
            domains = list(self._indices.keys())

        results: list[SearchResult] = []
        for did in domains:
            ix = self._indices[did]
            parser = MultifieldParser(["breadcrumb"], schema=ix.schema, group=OrGroup)
            q = parser.parse(query_str)
            with ix.searcher() as searcher:
                hits = searcher.search(q, limit=top_k)
                for i, hit in enumerate(hits):
                    results.append(SearchResult(
                        chunk_id=hit["chunk_id"],
                        breadcrumb=hit["breadcrumb"],
                        entity_id=hit.get("entity_id", ""),
                        entity_type=hit.get("entity_type", ""),
                        domain_id=hit.get("domain_id", did),
                        score=hit.score,
                        rank=i,
                        source="lucene",
                    ))

        results.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(results[:top_k]):
            r.rank = i
        return results[:top_k]

    def wipe_index(self, domain_id: str) -> None:
        domain_dir = self._base_dir / domain_id
        if domain_dir.exists():
            shutil.rmtree(domain_dir)
        self._indices.pop(domain_id, None)

    @property
    def is_ready(self) -> bool:
        return self._base_dir.exists()
