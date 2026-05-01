from __future__ import annotations

import logging
import re

from src.indexers.graph import GraphIndexWriter
from src.models.core import MetadataChunk, ParsedIntent, SearchResult

log = logging.getLogger(__name__)

# Valid Cypher statements must start with one of these keywords.
_CYPHER_START = re.compile(
    r"^\s*(MATCH|CALL|WITH|RETURN|UNWIND|MERGE|CREATE|OPTIONAL)\b",
    re.IGNORECASE,
)


class GraphSearch:
    def __init__(self, writer: GraphIndexWriter,
                 domain_ids: list[str] | None = None) -> None:
        self._writer = writer
        self._domain_ids = domain_ids or ["metadata"]

    def search(self, intent: ParsedIntent, top_k: int = 10,
               domain_id: str | None = None) -> list[SearchResult]:
        query = intent.expanded_query or ""
        if not query:
            return []

        label_filter = f"Chunk_{domain_id}" if domain_id else None
        valid_hints = [h for h in (intent.cypher_hints or []) if _CYPHER_START.match(h)]
        invalid = len((intent.cypher_hints or [])) - len(valid_hints)
        if invalid:
            log.info("Dropped %d malformed Cypher hint(s) that did not start with a valid keyword", invalid)

        results: list[SearchResult] = []

        if valid_hints:
            results = self._run_cypher_hints(valid_hints, domain_id, top_k)

        # Fall back to fulltext whenever hints were absent, all invalid, or produced nothing.
        if not results:
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
        labels = [label_filter] if label_filter else [f"Chunk_{did}" for did in self._domain_ids]
        terms = query.replace('"', '').split()[:5]
        conditions = " OR ".join(f'n.breadcrumb CONTAINS "{t}"' for t in terms)

        results: list[SearchResult] = []
        for label in labels:
            cypher = (
                f"MATCH (n:{label}) WHERE {conditions} "
                f"RETURN n.chunk_id AS chunk_id, n.breadcrumb AS breadcrumb, "
                f"n.entity_id AS entity_id, n.entity_type AS entity_type, "
                f"n.domain_id AS domain_id LIMIT {top_k}"
            )
            try:
                rows = self._writer.cypher_query(cypher)
                for i, row in enumerate(rows):
                    results.append(SearchResult(
                        chunk_id=str(row.get("chunk_id", f"g_{i}")),
                        breadcrumb=str(row.get("breadcrumb", "")),
                        entity_id=str(row.get("entity_id", "")),
                        entity_type=str(row.get("entity_type", "")),
                        domain_id=str(row.get("domain_id", "")),
                        score=1.0 / (i + 1), rank=i, source="graph",
                    ))
            except Exception as exc:
                log.warning("Graph fulltext search failed for %s: %s", label, exc)

        results.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(results[:top_k]):
            r.rank = i
        return results[:top_k]
