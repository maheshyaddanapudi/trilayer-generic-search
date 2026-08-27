from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import health_router, index_router, search_router
from src.domain.registry import DomainRegistry
from src.main import _NullGraphWriter, _run_sync, create_app
from src.models.core import IngestionResult, ParsedIntent, SearchResult


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_result(cid):
    return SearchResult(
        chunk_id=cid, score=0.9, breadcrumb=f"BC {cid}",
        entity_id=cid, entity_type="Account",
        domain_id="metadata", rank=0, source="vector",
    )


def _make_intent():
    return ParsedIntent(
        query_type="DISCOVERY", expanded_query="revenue",
        entity_hint="Account", confidence=0.92, cypher_hints=[],
    )


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(health_router)
    test_app.include_router(search_router)
    test_app.include_router(index_router)
    return test_app


@pytest.fixture
def full_state_app(app):
    """App with all state attributes mocked and ready."""
    registry = DomainRegistry.get_instance()
    meta_cfg = MagicMock()
    meta_cfg.domain_id = "metadata"
    doc_cfg = MagicMock()
    doc_cfg.domain_id = "documents"
    doc_cfg.graph_schema = MagicMock()
    registry.register(meta_cfg)
    registry.register(doc_cfg)

    graph_writer = MagicMock()
    graph_writer.is_ready = True
    graph_writer.cypher_query.return_value = [{"result": "ok"}]
    graph_writer.index_entities.return_value = 1
    graph_writer.index_relationships.return_value = 0

    vector_writer = MagicMock()
    vector_writer.is_ready = True
    vector_writer.clear_domain.return_value = 0

    lucene_writer = MagicMock()
    lucene_writer.is_ready = True

    mock_search_orch = MagicMock()
    mock_search_orch.run = AsyncMock(return_value={
        "query": "revenue",
        "domain": "metadata",
        "final_results": [_make_result("c1")],
        "intent": _make_intent(),
        "synthesis": "SAAS_REVENUE is a recurring revenue account.",
        "latency_ms": 42.0,
    })

    mock_ingest_orch = MagicMock()
    mock_ingest_orch.ingest_domain.return_value = IngestionResult(
        domain_id="metadata",
        entities_ingested=5,
        chunks_indexed=5,
        graph_nodes=5,
        duration_ms=100.0,
    )
    mock_ingest_orch._fan_out = MagicMock()

    breadcrumb_gen = MagicMock()
    breadcrumb_gen.generate.return_value = MagicMock(
        chunk_id="doc1_sec1",
        domain_id="documents",
        entity_id="sec1",
        entity_type="Section",
        breadcrumb="BC sec1",
    )

    app.state.graph_writer = graph_writer
    app.state.vector_writer = vector_writer
    app.state.lucene_writer = lucene_writer
    app.state.registry = registry
    app.state.search_orchestrator = mock_search_orch
    app.state.ingest_orchestrator = mock_ingest_orch
    app.state.breadcrumb_gen = breadcrumb_gen
    app.state.indexed_docs = {}

    # Wire document connector mock
    doc_connector = MagicMock()
    doc_entity = MagicMock()
    doc_entity.entity_type = "Document"
    doc_entity.entity_id = "doc1"
    doc_entity.name = "Test Doc"
    section_entity = MagicMock()
    section_entity.entity_type = "Section"
    section_entity.entity_id = "sec1"
    doc_connector.process_upload.return_value = [doc_entity, section_entity]
    doc_cfg.connector = doc_connector

    return app


# ── Health endpoint ───────────────────────────────────────────────────────────

def test_health_ok(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["neo4j_ok"] is True
    assert data["vector_ok"] is True
    assert data["lucene_ok"] is True
    assert data["metadata_domain"] is True
    assert data["documents_domain"] is True
    assert data["uptime_seconds"] >= 0


def test_health_no_registry(app):
    # No state at all → everything False
    app.state.graph_writer = MagicMock(is_ready=False)
    app.state.vector_writer = MagicMock(is_ready=False)
    app.state.lucene_writer = MagicMock(is_ready=False)
    # No registry set
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata_domain"] is False
    assert data["documents_domain"] is False


def test_health_writers_not_ready(app):
    registry = DomainRegistry.get_instance()
    app.state.registry = registry
    app.state.graph_writer = MagicMock(is_ready=False)
    app.state.vector_writer = MagicMock(is_ready=False)
    app.state.lucene_writer = MagicMock(is_ready=False)
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["neo4j_ok"] is False


# ── Per-domain health (registered vs. indexed) ────────────────────────────────

def test_health_domain_indexed_when_chunks_present(full_state_app):
    """When count_domain returns >0, the domain reports indexed=True."""
    full_state_app.state.vector_writer.count_domain = MagicMock(
        side_effect=lambda d: 33 if d == "metadata" else 942
    )
    with TestClient(full_state_app) as c:
        data = c.get("/health").json()

    assert data["metadata"]["registered"] is True
    assert data["metadata"]["indexed"] is True
    assert data["metadata"]["chunk_count"] == 33
    assert data["documents"]["registered"] is True
    assert data["documents"]["indexed"] is True
    assert data["documents"]["chunk_count"] == 942


def test_health_domain_not_indexed_when_zero_rows(full_state_app):
    """Registered but no rows in the vector store → indexed=False."""
    full_state_app.state.vector_writer.count_domain = MagicMock(return_value=0)
    with TestClient(full_state_app) as c:
        data = c.get("/health").json()

    assert data["metadata"]["registered"] is True
    assert data["metadata"]["indexed"] is False
    assert data["metadata"]["chunk_count"] == 0


def test_health_domain_count_swallows_writer_errors(full_state_app):
    """count_domain raising must not crash /health — it returns 0 instead."""
    full_state_app.state.vector_writer.count_domain = MagicMock(
        side_effect=RuntimeError("vector store down")
    )
    with TestClient(full_state_app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["chunk_count"] == 0
    assert data["metadata"]["indexed"] is False


def test_health_domain_unregistered_reports_zero(app):
    """Unregistered domains never call count_domain and report all-False."""
    app.state.graph_writer = MagicMock(is_ready=False)
    app.state.vector_writer = MagicMock(is_ready=False)
    app.state.lucene_writer = MagicMock(is_ready=False)
    # No registry on state → both domains unregistered.
    with TestClient(app) as c:
        data = c.get("/health").json()

    assert data["metadata"]["registered"] is False
    assert data["metadata"]["indexed"] is False
    assert data["metadata"]["chunk_count"] == 0
    assert data["documents"]["registered"] is False
    assert data["documents"]["chunk_count"] == 0


# ── Search endpoint ───────────────────────────────────────────────────────────

def test_search_post_ok(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/search", json={"query": "revenue", "domain": "metadata", "top_k": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "revenue"
    assert len(data["results"]) == 1
    assert data["synthesis"] == "SAAS_REVENUE is a recurring revenue account."
    assert data["latency_ms"] == 42.0


def test_search_null_domain(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/search", json={"query": "revenue"})
    assert resp.status_code == 200
    assert resp.json()["domain"] is None


def test_search_domain_not_in_registry(app):
    # "documents" is a valid Literal value but not registered → 404
    registry = DomainRegistry.get_instance()
    meta_cfg = MagicMock()
    meta_cfg.domain_id = "metadata"
    registry.register(meta_cfg)
    app.state.registry = registry
    app.state.search_orchestrator = MagicMock()
    app.state.search_orchestrator.run = AsyncMock(return_value={
        "query": "x", "domain": "documents", "final_results": [],
        "synthesis": "", "latency_ms": 0.0,
    })
    with TestClient(app) as c:
        resp = c.post("/search", json={"query": "revenue", "domain": "documents"})
    assert resp.status_code == 404
    assert "not registered" in resp.json()["detail"]


def test_search_no_orchestrator(app):
    app.state.registry = DomainRegistry.get_instance()
    # No search_orchestrator set
    with TestClient(app) as c:
        resp = c.post("/search", json={"query": "revenue"})
    assert resp.status_code == 503


def test_search_intent_in_response(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/search", json={"query": "revenue", "domain": "metadata"})
    data = resp.json()
    assert "intent" in data
    assert data["intent"]["query_type"] == "DISCOVERY"
    assert data["intent"]["confidence"] == 0.92


def test_search_no_intent_in_state(full_state_app):
    # Override orchestrator to return state without intent
    full_state_app.state.search_orchestrator.run = AsyncMock(return_value={
        "query": "revenue",
        "domain": None,
        "final_results": [],
        "synthesis": "",
        "latency_ms": 1.0,
    })
    with TestClient(full_state_app) as c:
        resp = c.post("/search", json={"query": "revenue"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == {}


# ── Metadata index endpoint ───────────────────────────────────────────────────

def test_index_metadata_ok(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/domains/metadata/index", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "metadata"
    assert data["entities_indexed"] == 5
    assert data["chunks_indexed"] == 5


def test_index_metadata_no_ingest_orchestrator(app):
    app.state.registry = DomainRegistry.get_instance()
    with TestClient(app) as c:
        resp = c.post("/domains/metadata/index", json={})
    assert resp.status_code == 503


# ── Document upload endpoint ──────────────────────────────────────────────────

def test_upload_too_large(full_state_app):
    big_content = b"x" * (20 * 1024 * 1024 + 1)
    with TestClient(full_state_app) as c:
        resp = c.post(
            "/domains/documents/files/upload",
            files={"file": ("test.pdf", big_content, "application/pdf")},
        )
    assert resp.status_code == 413


def test_upload_unsupported_mime(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post(
            "/domains/documents/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
    assert resp.status_code == 415
    assert "Unsupported" in resp.json()["detail"]


def test_upload_no_doc_entity(full_state_app):
    # Override connector to return only section entities (no Document entity)
    doc_cfg = full_state_app.state.registry.get("documents")
    doc_cfg.connector.process_upload.return_value = []
    with TestClient(full_state_app) as c:
        resp = c.post(
            "/domains/documents/files/upload",
            files={"file": ("test.pdf", b"%PDF-1.4 minimal", "application/pdf")},
        )
    assert resp.status_code == 422


def test_upload_pdf_ok(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post(
            "/domains/documents/files/upload",
            files={"file": ("test.pdf", b"%PDF-1.4 content", "application/pdf")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["doc_id"] == "doc1"
    assert data["title"] == "Test Doc"
    assert data["sections_indexed"] == 1


def test_upload_graph_index_failure_continues(full_state_app):
    full_state_app.state.graph_writer.index_entities.side_effect = Exception("graph down")
    with TestClient(full_state_app) as c:
        resp = c.post(
            "/domains/documents/files/upload",
            files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
        )
    assert resp.status_code == 200


# ── List documents endpoint ───────────────────────────────────────────────────

def test_list_documents_empty(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.get("/domains/documents/files")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_documents_populated(full_state_app):
    full_state_app.state.indexed_docs = {"doc1": "Revenue Policy", "doc2": "CapEx Guide"}
    with TestClient(full_state_app) as c:
        resp = c.get("/domains/documents/files")
    assert resp.status_code == 200
    ids = {d["doc_id"] for d in resp.json()}
    assert "doc1" in ids
    assert "doc2" in ids


# ── Delete document endpoint ──────────────────────────────────────────────────

def test_delete_document_ok(full_state_app):
    full_state_app.state.indexed_docs = {"doc1": "Revenue Policy"}
    with TestClient(full_state_app) as c:
        resp = c.delete("/domains/documents/files/doc1")
    assert resp.status_code == 204
    assert "doc1" not in full_state_app.state.indexed_docs


def test_delete_document_not_found(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.delete("/domains/documents/files/nonexistent")
    assert resp.status_code == 404


def test_delete_document_vector_clear_failure_continues(full_state_app):
    full_state_app.state.indexed_docs = {"doc1": "Title"}
    full_state_app.state.vector_writer.clear_domain.side_effect = Exception("clear failed")
    with TestClient(full_state_app) as c:
        resp = c.delete("/domains/documents/files/doc1")
    assert resp.status_code == 204


# ── Debug cypher endpoint ─────────────────────────────────────────────────────

def test_debug_cypher_ok(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/debug/cypher", json={"cypher": "MATCH (n) RETURN n LIMIT 1"})
    assert resp.status_code == 200
    full_state_app.state.graph_writer.cypher_query.assert_called_once()


def test_debug_cypher_with_params(full_state_app):
    full_state_app.state.graph_writer.cypher_query.return_value = []
    with TestClient(full_state_app) as c:
        resp = c.post("/debug/cypher",
                      json={"cypher": "MATCH (n) WHERE n.code = $code RETURN n",
                            "params": {"code": "REVENUE"}})
    assert resp.status_code == 200


def test_debug_cypher_missing_field(full_state_app):
    with TestClient(full_state_app) as c:
        resp = c.post("/debug/cypher", json={"cypher": ""})
    assert resp.status_code == 422


# ── _NullGraphWriter (main.py) ────────────────────────────────────────────────

def test_null_graph_writer_index():
    nw = _NullGraphWriter()
    assert nw.index([]) == 0


def test_null_graph_writer_index_entities():
    nw = _NullGraphWriter()
    assert nw.index_entities([], MagicMock()) == 0


def test_null_graph_writer_index_relationships():
    nw = _NullGraphWriter()
    assert nw.index_relationships([], MagicMock()) == 0


def test_null_graph_writer_get_neighbours():
    nw = _NullGraphWriter()
    assert nw.get_neighbours(["c1"], ["PARENT_OF"]) == []


def test_null_graph_writer_get_ancestors():
    nw = _NullGraphWriter()
    assert nw.get_ancestors("X", "Account") == []


def test_null_graph_writer_cypher_query():
    nw = _NullGraphWriter()
    assert nw.cypher_query("MATCH (n) RETURN n") == []


def test_null_graph_writer_close():
    nw = _NullGraphWriter()
    nw.close()  # should not raise


def test_null_graph_writer_is_ready():
    nw = _NullGraphWriter()
    assert nw.is_ready is False


# ── create_app and _run_sync (main.py) ────────────────────────────────────────

def test_create_app_returns_fastapi():
    app = create_app()
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_create_app_has_routes():
    app = create_app()
    paths = {r.path for r in app.routes}
    assert "/health" in paths
    assert "/search" in paths
    assert "/domains/metadata/index" in paths


def test_run_sync_returns_value():
    result = asyncio.run(_run_sync(lambda: 42))
    assert result == 42


def test_run_sync_with_args():
    result = asyncio.run(_run_sync(lambda a, b: a + b, 3, 4))
    assert result == 7


# ── Lifespan tests (covers main.py:35-119) ────────────────────────────────────

def _make_lifespan_mocks():
    """Build all the sys.modules mocks needed to run lifespan."""
    mock_neo4j = MagicMock()
    mock_driver_obj = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run.return_value = iter([])
    mock_driver_obj.session.return_value = mock_session
    mock_neo4j.GraphDatabase.driver.return_value = mock_driver_obj

    mock_st = MagicMock()
    mock_st_model = MagicMock()
    mock_st_model.encode.side_effect = (
        lambda texts, **kw: np.zeros((len(texts), 384), dtype=np.float32)
    )
    mock_st.SentenceTransformer.return_value = mock_st_model

    mock_psycopg2 = MagicMock()
    mock_pg_conn2 = MagicMock()
    mock_pg_cursor2 = MagicMock()
    mock_pg_cursor2.__enter__ = lambda s: mock_pg_cursor2
    mock_pg_cursor2.__exit__ = MagicMock(return_value=False)
    mock_pg_cursor2.fetchall.return_value = []
    mock_pg_cursor2.rowcount = 0
    mock_pg_conn2.cursor.return_value = mock_pg_cursor2
    mock_psycopg2.connect.return_value = mock_pg_conn2

    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = MagicMock()

    return {
        "neo4j": mock_neo4j,
        "sentence_transformers": mock_st,
        "psycopg2": mock_psycopg2,
        "anthropic": mock_anthropic_mod,
    }, mock_neo4j


def _make_mock_settings(tmp_path, whoosh_dir, sample_xml_path):
    s = MagicMock()
    s.neo4j_uri = "bolt://localhost:7687"
    s.neo4j_user = "neo4j"
    s.neo4j_password = "password"
    s.embedding_model = "all-MiniLM-L6-v2"
    s.postgres_url = "postgresql://localhost/test"
    s.postgres_vector_table = "metadata_chunks"
    s.embedding_dimension = 384
    s.whoosh_index_dir = str(whoosh_dir)
    s.metadata_file = str(sample_xml_path)
    s.uploads_dir = str(tmp_path)
    s.llm_provider = "anthropic"
    s.anthropic_api_key = "sk-test"
    s.intent_model = "claude-haiku-4-5-20251001"
    s.synthesis_model = "claude-sonnet-4-6"
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_intent_model = "gemma4:31b"
    s.ollama_synthesis_model = "gemma4:31b"
    s.ollama_request_timeout_s = 180.0
    s.rrf_k = 60
    s.graph_boost_factor = 1.5
    s.graph_boost_top_n = 3
    return s


def test_lifespan_happy_path(tmp_path, sample_xml_path):
    whoosh_dir = tmp_path / "whoosh"
    whoosh_dir.mkdir()

    mock_modules, _ = _make_lifespan_mocks()
    mock_settings = _make_mock_settings(tmp_path, whoosh_dir, sample_xml_path)

    with patch.dict(sys.modules, mock_modules), \
         patch("src.main.get_settings", return_value=mock_settings):
        with TestClient(create_app()) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


def test_lifespan_neo4j_unavailable(tmp_path, sample_xml_path):
    # L45-47: neo4j import/driver raises → falls back to _NullGraphWriter
    whoosh_dir = tmp_path / "whoosh_neo4j_fail"
    whoosh_dir.mkdir()

    mock_modules, mock_neo4j = _make_lifespan_mocks()
    mock_neo4j.GraphDatabase.driver.side_effect = Exception("connection refused")

    mock_settings = _make_mock_settings(tmp_path, whoosh_dir, sample_xml_path)

    with patch.dict(sys.modules, mock_modules), \
         patch("src.main.get_settings", return_value=mock_settings):
        with TestClient(create_app()) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        # _NullGraphWriter → neo4j_ok = False
        assert data["neo4j_ok"] is False
