from __future__ import annotations

from src.aggregation.base import ResultPostProcessor
from src.models.core import SearchResult


class RRFAggregator(ResultPostProcessor):
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank_i)."""

    def __init__(self, k: int = 60) -> None:
        self._k = k

    def process(self, results: list[SearchResult], top_k: int = 10,
                **kwargs) -> list[SearchResult]:
        scores: dict[str, float] = {}
        best: dict[str, SearchResult] = {}

        for result in results:
            cid = result.chunk_id
            rrf_score = 1.0 / (self._k + result.rank + 1)
            scores[cid] = scores.get(cid, 0.0) + rrf_score
            if cid not in best or result.score > best[cid].score:
                best[cid] = result

        merged = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
        out: list[SearchResult] = []
        for rank, cid in enumerate(merged[:top_k]):
            r = best[cid]
            out.append(SearchResult(
                chunk_id=r.chunk_id, score=scores[cid],
                breadcrumb=r.breadcrumb, entity_id=r.entity_id,
                entity_type=r.entity_type, domain_id=r.domain_id,
                rank=rank, source=r.source,
            ))
        return out
