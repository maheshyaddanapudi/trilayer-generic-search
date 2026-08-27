from __future__ import annotations

from src.aggregation.base import ResultPostProcessor
from src.indexers.graph import GraphIndexWriter
from src.models.core import SearchResult


class GraphBoostingAggregator(ResultPostProcessor):
    def __init__(self, graph_writer: GraphIndexWriter,
                 boost_factor: float = 1.5, top_n: int = 3) -> None:
        self._graph = graph_writer
        self._boost_factor = boost_factor
        self._top_n = top_n

    def process(self, results: list[SearchResult], top_k: int = 10,
                lucene_results: list[SearchResult] | None = None,
                **kwargs) -> list[SearchResult]:
        if not results:
            return results

        seed = (lucene_results or [])[:self._top_n]
        if not seed:
            return results

        seed_ids = [r.chunk_id for r in seed]
        try:
            neighbours = self._graph.get_neighbours(
                seed_ids, ["PARENT_OF", "LINKED_TO", "HAS_SECTION"], depth=1
            )
        except Exception:
            return results

        neighbour_ids = {n.chunk_id for n in neighbours}
        boosted: list[SearchResult] = []
        for r in results:
            if r.chunk_id in neighbour_ids:
                boosted.append(SearchResult(
                    chunk_id=r.chunk_id,
                    score=r.score * self._boost_factor,
                    breadcrumb=r.breadcrumb, entity_id=r.entity_id,
                    entity_type=r.entity_type, domain_id=r.domain_id,
                    rank=r.rank, source=r.source,
                ))
            else:
                boosted.append(r)

        boosted.sort(key=lambda x: x.score, reverse=True)
        for i, r in enumerate(boosted):
            r.rank = i
        return boosted
