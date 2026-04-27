from __future__ import annotations

import numpy as np
import pytest

from src.indexers.vector import VectorIndexWriter
from src.models.core import MetadataChunk


def _chunk(cid, domain="metadata"):
    return MetadataChunk(chunk_id=cid, domain_id=domain, entity_id=cid,
                         entity_type="Account", breadcrumb=f"BC {cid}")


def _make_writer(mock_pg_conn, mock_model):
    return VectorIndexWriter(conn=mock_pg_conn, model=mock_model,
                             table="metadata_chunks", dimension=384)


def test_setup_schema_called_on_init(mock_pg_conn, mock_model):
    _make_writer(mock_pg_conn, mock_model)
    # commit should be called during schema setup
    assert mock_pg_conn.commit.called


def test_index_empty_returns_zero(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    assert writer.index([]) == 0


def test_index_calls_model_encode(mock_pg_conn, mock_model):
    mock_model.encode.return_value = np.zeros((2, 384), dtype=np.float32)
    writer = _make_writer(mock_pg_conn, mock_model)
    chunks = [_chunk("c1"), _chunk("c2")]
    count = writer.index(chunks)
    assert count == 2
    mock_model.encode.assert_called_once()


def test_index_commits(mock_pg_conn, mock_model):
    mock_model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    writer = _make_writer(mock_pg_conn, mock_model)
    mock_pg_conn.commit.reset_mock()
    writer.index([_chunk("c1")])
    assert mock_pg_conn.commit.called


def test_similarity_search_domain_scoped(mock_pg_conn, mock_model):
    mock_pg_conn.cursor.return_value.fetchall.return_value = [
        ("c1", "BC c1", "c1", "Account", "metadata", 0.9),
    ]
    writer = _make_writer(mock_pg_conn, mock_model)
    results = writer.similarity_search([0.0] * 384, top_k=5, domain_id="metadata")
    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].source == "vector"


def test_similarity_search_full_scope(mock_pg_conn, mock_model):
    mock_pg_conn.cursor.return_value.fetchall.return_value = []
    writer = _make_writer(mock_pg_conn, mock_model)
    results = writer.similarity_search([0.0] * 384, top_k=5, domain_id=None)
    assert results == []


def test_clear_domain_returns_rowcount(mock_pg_conn, mock_model):
    mock_pg_conn.cursor.return_value.rowcount = 5
    writer = _make_writer(mock_pg_conn, mock_model)
    count = writer.clear_domain("metadata")
    assert count == 5
    assert mock_pg_conn.commit.called


def test_is_ready_true(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    assert writer.is_ready is True


def test_is_ready_false_on_exception(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    mock_pg_conn.cursor.side_effect = Exception("db down")
    assert writer.is_ready is False


def test_count_domain_returns_row_count(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    mock_pg_conn.cursor.return_value.fetchone.return_value = (42,)
    assert writer.count_domain("metadata") == 42


def test_count_domain_empty_table_returns_zero(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    mock_pg_conn.cursor.return_value.fetchone.return_value = None
    assert writer.count_domain("metadata") == 0


def test_count_domain_swallows_db_errors(mock_pg_conn, mock_model):
    writer = _make_writer(mock_pg_conn, mock_model)
    # Schema setup is done; flip to error mode for the count query.
    mock_pg_conn.cursor.side_effect = Exception("db down")
    assert writer.count_domain("metadata") == 0
