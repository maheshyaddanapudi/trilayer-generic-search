from __future__ import annotations

import logging

from src.indexers.graph import GraphIndexWriter
from src.models.core import MetadataChunk, ParsedIntent, SearchResult

log = logging.getLogger(__name__)


class GraphSearch:
    def __init__(self, writer: GraphIndexWriter) -> None:
        self._writer = writer

    def search(self, intent: ParsedIntent, top_k: int = 10,
               domain_id: str | None = None) -> list[SearchResult]:
        query = intent.expanded_query or ""
        if not query:
            return []

        label_filter = f"Chunk_{domain_id}" if domain_id else None
        cypher_hints = intent.cypher_hints or []

        results: list[SearchResult] = []

        if cypher_hints:
            results = self._run_cypher_hints(cypher_hints, domain_id, top_k)
        else:
            results = self._fulltext_search(query, label_filter, top_k)

        return results[:top_k]

    def _run_cypher_hints(self, hints: list[str], domain_id: str | None,
                          top_k: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for hint in hints:
            try:
                rows = self._writer.cypher_query(hint)
                for i, row in enumerate(rows[:top_k]):
                    chunk_id = str(row.get("chunk_id", row.get("cid", f"graph_{i}")))
                    breadcrumb = str(row.get("breadcrumb", row.get("name", "")))
                    results.append(SearchResult(
                        chunk_id=chunk_id, breadcrumb=breadcrumb,
                        entity_id=str(row.get("entity_id", "")),
                        entity_type=str(row.get("entity_type", "")),
                        domain_id=domain_id or "",
                        score=1.0 / (i + 1), rank=i, source="graph",
                    ))
            except Exception as exc:
                log.warning("Cypher hint failed: %s", exc)
        return results

    def _fulltext_search(self, query: str, label_filter: str | None,
                         top_k: int) -> list[SearchResult]:
        label = label_filter or "Chunk_metadata"
        terms = query.replace('"', '').split()[:5]
        conditions = " OR ".join(f'n.breadcrumb CONTAINS "{t}"' for t in terms)
        cypher = (
            f"MATCH (n:{label}) WHERE {conditions} "
            f"RETURN n.chunk_id AS chunk_id, n.breadcrumb AS breadcrumb, "
            f"n.entity_id AS entity_id, n.entity_type AS entity_type, "
            f"n.domain_id AS domain_id LIMIT {top_k}"
        )
        try:
            rows = self._writer.cypher_query(cypher)
            return [
                SearchResult(
                    chunk_id=str(row.get("chunk_id", f"g_{i}")),
                    breadcrumb=str(row.get("breadcrumb", "")),
                    entity_id=str(row.get("entity_id", "")),
                    entity_type=str(row.get("entity_type", "")),
                    domain_id=str(row.get("domain_id", "")),
                    score=1.0 / (i + 1), rank=i, source="graph",
                )
                for i, row in enumerate(rows)
            ]
        except Exception as exc:
            log.warning("Graph fulltext search failed: %s", exc)
            return []
