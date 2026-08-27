from __future__ import annotations

from datetime import datetime

from src.models.core import (
    IngestionMode, IngestionResult, MetadataChunk, ParsedIntent,
    RawEntity, RawRelationship, SearchResult, SearchState,
)


def test_raw_relationship_defaults():
    r = RawRelationship(source_id="A", target_id="B", relation_type="PARENT_OF")
    assert r.properties == {}


def test_raw_entity_defaults():
    e = RawEntity(entity_id="X", entity_type="Account", domain_id="metadata", name="X")
    assert e.description == ""
    assert e.properties == {}
    assert e.parent_id is None
    assert e.relationships == []
    assert isinstance(e.ingested_at, datetime)


def test_raw_entity_with_relationships():
    rel = RawRelationship("P", "C", "PARENT_OF")
    e = RawEntity("C", "Account", "metadata", "Child", parent_id="P", relationships=[rel])
    assert len(e.relationships) == 1


def test_metadata_chunk_defaults():
    c = MetadataChunk(chunk_id="c1", domain_id="metadata", entity_id="E",
                      entity_type="Account", breadcrumb="E | Account | Metadata")
    assert c.embedding is None
    assert c.properties == {}
    assert isinstance(c.created_at, datetime)


def test_search_result_defaults():
    r = SearchResult(chunk_id="c1", score=0.9, breadcrumb="B",
                     entity_id="E", entity_type="Account", domain_id="metadata")
    assert r.rank == 0
    assert r.source == ""


def test_parsed_intent_defaults():
    p = ParsedIntent(query_type="DISCOVERY", expanded_query="revenue")
    assert p.entity_hint is None
    assert p.confidence == 0.0
    assert p.cypher_hints == []
    assert p.scope_filters == {}


def test_ingestion_result():
    r = IngestionResult(domain_id="metadata", entities_ingested=10,
                        chunks_indexed=10, graph_nodes=10, duration_ms=250.0)
    assert r.errors == []


def test_ingestion_mode_values():
    assert IngestionMode.FULL == "full"
    assert IngestionMode.INCREMENTAL == "incremental"


def test_search_state_typeddict():
    state: SearchState = {"query": "test", "domain": None, "top_k": 10}
    assert state["query"] == "test"
    assert state["domain"] is None
