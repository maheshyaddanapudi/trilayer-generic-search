from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.aggregation.base import AggregationPipeline
from src.domain.registry import DomainRegistry
from src.models.core import ParsedIntent, SearchResult, SearchState
from src.search.graph_search import GraphSearch
from src.search.lucene_search import LuceneSearch
from src.search.orchestrator import SearchOrchestrator
from src.search.vector_search import VectorSearch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _intent(query="revenue", query_type="DISCOVERY", cypher_hints=None):
    return ParsedIntent(
        query_type=query_type,
        expanded_query=query,
        entity_hint="Account",
        confidence=0.9,
        cypher_hints=cypher_hints or [],
    )


def _result(cid, source="vector"):
    return SearchResult(
        chunk_id=cid, score=1.0, breadcrumb=f"BC {cid}",
        entity_id=cid, entity_type="Account",
        domain_id="metadata", rank=0, source=source,
    )


def _make_orchestrator(vector_results=None, lucene_results=None, graph_results=None,
                       synthesis="answer"):
    registry = DomainRegistry()
    mock_cfg = MagicMock()
    mock_cfg.domain_id = "metadata"
    mock_cfg.graph_boost_factor = 1.5
    registry.register(mock_cfg)

    v_writer = MagicMock()
    v_writer.similarity_search.return_value = vector_results or []
    v_model = MagicMock()
    v_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    vector_search = VectorSearch(v_writer, v_model)

    l_writer = MagicMock()
    l_writer.keyword_search.return_value = lucene_results or []
    lucene_search = LuceneSearch(l_writer)

    g_writer = MagicMock()
    g_writer.cypher_query.return_value = []
    graph_search = GraphSearch(g_writer)

    intent_parser = MagicMock()
    intent_parser.parse.return_value = _intent()

    synthesizer = MagicMock()
    synthesizer.synthesize.return_value = synthesis

    agg = AggregationPipeline([])

    orch = SearchOrchestrator(
        vector_search=vector_search,
        lucene_search=lucene_search,
        graph_search=graph_search,
        intent_parser=intent_parser,
        synthesizer=synthesizer,
        aggregation_pipeline=agg,
        domain_registry=registry,
    )
    return orch, registry


# ── VectorSearch ──────────────────────────────────────────────────────────────

def test_vector_search_empty_query():
    writer = MagicMock()
    model = MagicMock()
    vs = VectorSearch(writer, model)
    intent = _intent(query="")
    assert vs.search(intent) == []
    model.encode.assert_not_called()


def test_vector_search_calls_encode_and_similarity():
    writer = MagicMock()
    writer.similarity_search.return_value = [_result("c1")]
    model = MagicMock()
    model.encode.return_value = np.array([[0.1] * 384], dtype=np.float32)
    vs = VectorSearch(writer, model)
    results = vs.search(_intent("revenue"), top_k=5, domain_id="metadata")
    model.encode.assert_called_once()
    writer.similarity_search.assert_called_once()
    assert len(results) == 1
    assert results[0].chunk_id == "c1"


# ── LuceneSearch ──────────────────────────────────────────────────────────────

def test_lucene_search_empty_query():
    writer = MagicMock()
    ls = LuceneSearch(writer)
    assert ls.search(_intent("")) == []
    writer.keyword_search.assert_not_called()


def test_lucene_search_calls_keyword_search():
    writer = MagicMock()
    writer.keyword_search.return_value = [_result("c2", "lucene")]
    ls = LuceneSearch(writer)
    results = ls.search(_intent("revenue"), top_k=5, domain_id="metadata")
    writer.keyword_search.assert_called_once_with("revenue", 5, domain_id="metadata")
    assert results[0].chunk_id == "c2"


# ── GraphSearch ───────────────────────────────────────────────────────────────

def test_graph_search_empty_query():
    writer = MagicMock()
    gs = GraphSearch(writer)
    assert gs.search(_intent("")) == []


def test_graph_search_fulltext_no_domain():
    writer = MagicMock()
    writer.cypher_query.return_value = [
        {"chunk_id": "c1", "breadcrumb": "BC c1", "entity_id": "c1",
         "entity_type": "Account", "domain_id": "metadata"},
    ]
    gs = GraphSearch(writer)
    results = gs.search(_intent("revenue"), domain_id=None)
    assert len(results) == 1
    assert results[0].source == "graph"


def test_graph_search_fulltext_domain_scoped():
    writer = MagicMock()
    writer.cypher_query.return_value = []
    gs = GraphSearch(writer)
    gs.search(_intent("revenue"), domain_id="metadata")
    call_args = writer.cypher_query.call_args[0][0]
    assert "Chunk_metadata" in call_args


def test_graph_search_cypher_hints():
    writer = MagicMock()
    writer.cypher_query.return_value = [
        {"chunk_id": "c3", "breadcrumb": "BC c3", "entity_id": "c3",
         "entity_type": "Account"},
    ]
    gs = GraphSearch(writer)
    intent = _intent("revenue", cypher_hints=["MATCH (n) RETURN n"])
    results = gs.search(intent, domain_id="metadata")
    assert len(results) >= 1
    assert results[0].chunk_id == "c3"


def test_graph_search_cypher_hint_failure_continues():
    writer = MagicMock()
    writer.cypher_query.side_effect = Exception("graph down")
    gs = GraphSearch(writer)
    intent = _intent("revenue", cypher_hints=["MATCH (n) RETURN n"])
    results = gs.search(intent, domain_id="metadata")
    assert results == []


def test_graph_search_fulltext_failure():
    writer = MagicMock()
    writer.cypher_query.side_effect = Exception("graph down")
    gs = GraphSearch(writer)
    results = gs.search(_intent("revenue"), domain_id="metadata")
    assert results == []


# ── SearchOrchestrator — nodes in isolation ───────────────────────────────────

def test_parse_intent_node():
    orch, _ = _make_orchestrator()
    state: SearchState = {"query": "revenue", "domain": "metadata", "top_k": 5}
    result = asyncio.run(orch._parse_intent_node(state))
    assert "intent" in result
    assert result["intent"].query_type == "DISCOVERY"


def test_triple_search_node_all_succeed():
    orch, _ = _make_orchestrator(
        vector_results=[_result("v1")],
        lucene_results=[_result("l1", "lucene")],
        graph_results=[],
    )
    orch._vector._writer.similarity_search.return_value = [_result("v1")]
    orch._lucene._writer.keyword_search.return_value = [_result("l1", "lucene")]

    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "intent": _intent("revenue"),
    }
    result = asyncio.run(orch._triple_search_node(state))
    assert isinstance(result["vector_results"], list)
    assert isinstance(result["lucene_results"], list)
    assert isinstance(result["graph_results"], list)


def test_triple_search_node_one_failure():
    orch, _ = _make_orchestrator()
    # Make vector search fail
    orch._vector._model.encode.side_effect = Exception("encode down")

    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "intent": _intent("revenue"),
    }
    result = asyncio.run(orch._triple_search_node(state))
    assert result["vector_results"] == []
    # lucene and graph still return lists
    assert isinstance(result["lucene_results"], list)
    assert isinstance(result["graph_results"], list)


def test_aggregate_node():
    orch, _ = _make_orchestrator()
    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "intent": _intent("revenue"),
        "vector_results": [_result("v1")],
        "lucene_results": [_result("l1", "lucene")],
        "graph_results": [],
    }
    result = asyncio.run(orch._aggregate_node(state))
    assert "final_results" in result
    assert isinstance(result["final_results"], list)


def test_aggregate_node_unknown_domain():
    orch, _ = _make_orchestrator()
    state: SearchState = {
        "query": "revenue", "domain": "unknown_domain", "top_k": 5,
        "intent": _intent("revenue"),
        "vector_results": [],
        "lucene_results": [],
        "graph_results": [],
    }
    # Should not raise even if domain not in registry
    result = asyncio.run(orch._aggregate_node(state))
    assert "final_results" in result


def test_synthesize_node():
    orch, _ = _make_orchestrator(synthesis="revenue is tracked here")
    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "final_results": [_result("v1")],
    }
    result = asyncio.run(orch._synthesize_node(state))
    assert result["synthesis"] == "revenue is tracked here"


def test_synthesize_node_no_domain():
    orch, _ = _make_orchestrator(synthesis="ok")
    state: SearchState = {
        "query": "revenue", "domain": None, "top_k": 5,
        "final_results": [_result("v1")],
    }
    result = asyncio.run(orch._synthesize_node(state))
    assert result["synthesis"] == "ok"


# ── SearchOrchestrator — full pipeline ───────────────────────────────────────

def test_run_full_pipeline():
    orch, _ = _make_orchestrator(
        vector_results=[_result("v1")],
        lucene_results=[_result("l1", "lucene")],
        synthesis="found revenue accounts",
    )
    state = asyncio.run(orch.run("revenue", domain="metadata", top_k=5))
    assert state["query"] == "revenue"
    assert state["latency_ms"] >= 0
    assert "synthesis" in state


def test_run_domain_none():
    orch, _ = _make_orchestrator()
    state = asyncio.run(orch.run("revenue", domain=None, top_k=5))
    assert state["domain"] is None
    assert "final_results" in state


def test_run_returns_latency_ms():
    orch, _ = _make_orchestrator()
    state = asyncio.run(orch.run("test query"))
    assert isinstance(state["latency_ms"], float)
    assert state["latency_ms"] >= 0


def test_triple_search_lucene_failure_logged():
    # L93: Lucene search fails → vector_results[] and graph_results[] populated, lucene=[]
    orch, _ = _make_orchestrator(
        vector_results=[_result("v1")],
    )
    orch._lucene._writer.keyword_search.side_effect = Exception("lucene down")

    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "intent": _intent("revenue"),
    }
    result = asyncio.run(orch._triple_search_node(state))
    assert result["lucene_results"] == []
    assert isinstance(result["vector_results"], list)


def test_triple_search_graph_failure_logged():
    # L95: GraphSearch.search() itself raises (not caught internally) → graph_results=[]
    orch, _ = _make_orchestrator()
    # Mock the whole search method to raise so gather captures it as an exception
    orch._graph.search = MagicMock(side_effect=Exception("graph search broken"))

    state: SearchState = {
        "query": "revenue", "domain": "metadata", "top_k": 5,
        "intent": _intent("revenue"),
    }
    result = asyncio.run(orch._triple_search_node(state))
    assert result["graph_results"] == []
