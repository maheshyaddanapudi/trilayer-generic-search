from __future__ import annotations

import logging
from typing import Any

from src.indexers.base import IndexWriter
from src.models.core import MetadataChunk, SearchResult

log = logging.getLogger(__name__)

_CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector;"
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    chunk_id    TEXT        PRIMARY KEY,
    domain_id   TEXT        NOT NULL,
    entity_id   TEXT,
    entity_type TEXT,
    breadcrumb  TEXT        NOT NULL,
    embedding   vector({dim}),
    properties  JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);
"""
_CREATE_HNSW = """
CREATE INDEX IF NOT EXISTS {table}_embedding_idx
    ON {table} USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""
_CREATE_DOMAIN_IDX = "CREATE INDEX IF NOT EXISTS {table}_domain_idx ON {table} (domain_id);"

_UPSERT = """
INSERT INTO {table} (chunk_id, domain_id, entity_id, entity_type, breadcrumb, embedding, properties)
VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb)
ON CONFLICT (chunk_id) DO UPDATE SET
    breadcrumb = EXCLUDED.breadcrumb,
    embedding  = EXCLUDED.embedding,
    properties = EXCLUDED.properties,
    created_at = now();
"""

_SEARCH_SCOPED = """
SELECT chunk_id, breadcrumb, entity_id, entity_type, domain_id,
       1 - (embedding <=> %s::vector) AS score
FROM {table}
WHERE domain_id = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

_SEARCH_ALL = """
SELECT chunk_id, breadcrumb, entity_id, entity_type, domain_id,
       1 - (embedding <=> %s::vector) AS score
FROM {table}
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

_DELETE_DOMAIN = "DELETE FROM {table} WHERE domain_id = %s;"


class VectorIndexWriter(IndexWriter):
    def __init__(self, conn: Any, model: Any, table: str = "metadata_chunks",
                 dimension: int = 384) -> None:
        self._conn = conn
        self._model = model
        self._table = table
        self._dim = dimension
        self._setup_schema()

    def _setup_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_CREATE_EXTENSION)
            cur.execute(_CREATE_TABLE.format(table=self._table, dim=self._dim))
            cur.execute(_CREATE_HNSW.format(table=self._table))
            cur.execute(_CREATE_DOMAIN_IDX.format(table=self._table))
        self._conn.commit()

    def index(self, chunks: list[MetadataChunk]) -> int:
        if not chunks:
            return 0
        texts = [c.breadcrumb for c in chunks]
        vectors = self._model.encode(texts, normalize_embeddings=True).tolist()
        import json
        with self._conn.cursor() as cur:
            for chunk, vec in zip(chunks, vectors):
                cur.execute(
                    _UPSERT.format(table=self._table),
                    (chunk.chunk_id, chunk.domain_id, chunk.entity_id,
                     chunk.entity_type, chunk.breadcrumb,
                     str(vec), json.dumps(chunk.properties)),
                )
        self._conn.commit()
        return len(chunks)

    def similarity_search(self, query_vector: list[float], top_k: int,
                          domain_id: str | None = None) -> list[SearchResult]:
        vec_str = str(query_vector)
        with self._conn.cursor() as cur:
            if domain_id:
                cur.execute(
                    _SEARCH_SCOPED.format(table=self._table),
                    (vec_str, domain_id, vec_str, top_k),
                )
            else:
                cur.execute(
                    _SEARCH_ALL.format(table=self._table),
                    (vec_str, vec_str, top_k),
                )
            rows = cur.fetchall()

        return [
            SearchResult(
                chunk_id=row[0], breadcrumb=row[1], entity_id=row[2],
                entity_type=row[3], domain_id=row[4], score=float(row[5]),
                rank=i, source="vector",
            )
            for i, row in enumerate(rows)
        ]

    def clear_domain(self, domain_id: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(_DELETE_DOMAIN.format(table=self._table), (domain_id,))
            count = cur.rowcount
        self._conn.commit()
        return count

    def count_domain(self, domain_id: str) -> int:
        """Return the number of indexed chunks for the given domain.

        Used by ``/health`` to distinguish "domain registered" from
        "domain queryable". Returns 0 if the table or the domain is empty,
        and also 0 on any backend error so the health probe can never crash.
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM {self._table} WHERE domain_id = %s",
                    (domain_id,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    @property
    def is_ready(self) -> bool:
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {self._table} LIMIT 1;")
            return True
        except Exception:
            return False
