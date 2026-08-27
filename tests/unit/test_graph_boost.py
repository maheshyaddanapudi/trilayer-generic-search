from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.aggregation.graph_boost import GraphBoostingAggregator
from src.models.core import MetadataChunk, SearchResult


def _r(chunk_id, score=0.5, rank=0):
    return SearchResult(chunk_id=chunk_id, score=score, breadcrumb=f"bc",
                        entity_id=chunk_id, entity_type="Account",
                        domain_id="metadata", rank=rank, source="vector")


def _chunk(chunk_id):
    return MetadataChunk(chunk_id=chunk_id, domain_id="metadata",
                         entity_id=chunk_id, entity_type="Account", breadcrumb="")


def test_no_boost_when_no_lucene():
    graph = MagicMock()
    agg = GraphBoostingAggregator(graph, boost_factor=1.5, top_n=3)
    results = [_r("a"), _r("b")]
    out = agg.process(results, top_k=2, lucene_results=None)
    # No lucene seed → no boost, results unchanged
    assert [r.chunk_id for r in out] == ["a", "b"]
    graph.get_neighbours.assert_not_called()


def test_no_boost_when_empty_results():
    graph = MagicMock()
    agg = GraphBoostingAggregator(graph)
    assert agg.process([], lucene_results=[]) == []


def test_boost_applied_to_neighbour():
    graph = MagicMock()
    graph.get_neighbours.return_value = [_chunk("b")]

    agg = GraphBoostingAggregator(graph, boost_factor=2.0, top_n=1)
    lucene = [_r("a", score=0.8, rank=0)]
    results = [_r("a", score=0.8, rank=0), _r("b", score=0.5, rank=1)]
    out = agg.process(results, top_k=2, lucene_results=lucene)

    b_result = next(r for r in out if r.chunk_id == "b")
    assert b_result.score == pytest.approx(1.0)  # 0.5 * 2.0


def test_non_neighbour_not_boosted():
    graph = MagicMock()
    graph.get_neighbours.return_value = []  # no neighbours

    agg = GraphBoostingAggregator(graph, boost_factor=1.5, top_n=3)
    lucene = [_r("seed")]
    results = [_r("seed", score=1.0), _r("other", score=0.5)]
    out = agg.process(results, top_k=2, lucene_results=lucene)

    other = next(r for r in out if r.chunk_id == "other")
    assert other.score == pytest.approx(0.5)


def test_boost_re_sorts():
    graph = MagicMock()
    # "b" is a neighbour of "a" (the lucene seed)
    graph.get_neighbours.return_value = [_chunk("b")]

    agg = GraphBoostingAggregator(graph, boost_factor=10.0, top_n=1)
    lucene = [_r("a", score=0.9)]
    # "b" starts with lower score but should jump to top after boost
    results = [_r("a", score=0.9, rank=0), _r("b", score=0.1, rank=1)]
    out = agg.process(results, top_k=2, lucene_results=lucene)
    assert out[0].chunk_id == "b"


def test_graph_failure_returns_original():
    graph = MagicMock()
    graph.get_neighbours.side_effect = RuntimeError("graph down")

    agg = GraphBoostingAggregator(graph, boost_factor=1.5, top_n=3)
    lucene = [_r("seed")]
    results = [_r("a"), _r("b")]
    out = agg.process(results, top_k=2, lucene_results=lucene)
    # Should gracefully return original results
    assert len(out) == 2


def test_ranks_reassigned_after_boost():
    graph = MagicMock()
    graph.get_neighbours.return_value = [_chunk("b")]
    agg = GraphBoostingAggregator(graph, boost_factor=5.0, top_n=1)
    lucene = [_r("a", score=0.9)]
    results = [_r("a", score=0.9, rank=0), _r("b", score=0.3, rank=1)]
    out = agg.process(results, top_k=2, lucene_results=lucene)
    for i, r in enumerate(out):
        assert r.rank == i
