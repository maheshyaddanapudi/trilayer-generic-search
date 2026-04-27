from __future__ import annotations

from src.aggregation.rrf import RRFAggregator
from src.models.core import SearchResult


def _r(chunk_id, score=1.0, rank=0, source="vector", domain="metadata"):
    return SearchResult(chunk_id=chunk_id, score=score, breadcrumb=f"bc_{chunk_id}",
                        entity_id=chunk_id, entity_type="Account",
                        domain_id=domain, rank=rank, source=source)


def test_rrf_empty():
    agg = RRFAggregator()
    assert agg.process([]) == []


def test_rrf_single_source():
    agg = RRFAggregator(k=60)
    results = [_r("a", rank=0), _r("b", rank=1), _r("c", rank=2)]
    out = agg.process(results, top_k=3)
    assert [r.chunk_id for r in out] == ["a", "b", "c"]


def test_rrf_merges_across_sources():
    agg = RRFAggregator(k=60)
    # "a" appears in both vector and lucene → higher combined score than "b" vector only
    results = [
        _r("a", rank=0, source="vector"),
        _r("b", rank=1, source="vector"),
        _r("a", rank=0, source="lucene"),   # "a" again from lucene
    ]
    out = agg.process(results, top_k=2)
    assert out[0].chunk_id == "a"  # "a" should rank first due to two contributions


def test_rrf_top_k_respected():
    agg = RRFAggregator()
    results = [_r(str(i), rank=i) for i in range(20)]
    out = agg.process(results, top_k=5)
    assert len(out) == 5


def test_rrf_rank_assigned():
    agg = RRFAggregator()
    results = [_r("x", rank=0), _r("y", rank=1)]
    out = agg.process(results, top_k=2)
    assert out[0].rank == 0
    assert out[1].rank == 1


def test_rrf_score_formula():
    agg = RRFAggregator(k=60)
    results = [_r("only", rank=0)]
    out = agg.process(results, top_k=1)
    expected = 1.0 / (60 + 0 + 1)
    assert abs(out[0].score - expected) < 1e-9


def test_rrf_best_result_metadata_preserved():
    agg = RRFAggregator()
    results = [
        SearchResult("c1", score=0.9, breadcrumb="BC", entity_id="E1",
                     entity_type="Account", domain_id="metadata", rank=0, source="vector"),
    ]
    out = agg.process(results, top_k=1)
    assert out[0].breadcrumb == "BC"
    assert out[0].entity_id == "E1"
    assert out[0].source == "vector"
