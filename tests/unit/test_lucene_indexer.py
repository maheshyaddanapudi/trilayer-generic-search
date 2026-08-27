from __future__ import annotations

from pathlib import Path

import pytest

from src.indexers.lucene import LuceneIndexWriter
from src.models.core import MetadataChunk


def _chunk(cid, domain="metadata", breadcrumb=None):
    return MetadataChunk(chunk_id=cid, domain_id=domain, entity_id=cid,
                         entity_type="Account",
                         breadcrumb=breadcrumb or f"BC {cid} revenue account")


def test_index_empty_returns_zero(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    assert writer.index([]) == 0


def test_index_and_search(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.index([_chunk("c1", breadcrumb="SAAS_REVENUE Account metadata recurring")])
    results = writer.keyword_search("SAAS_REVENUE", top_k=5, domain_id="metadata")
    assert len(results) >= 1
    assert results[0].chunk_id == "c1"
    assert results[0].source == "lucene"


def test_index_creates_domain_subdirectory(tmp_path):
    base = tmp_path / "whoosh"
    writer = LuceneIndexWriter(index_dir=base)
    writer.index([_chunk("c1", domain="metadata")])
    assert (base / "metadata").exists()


def test_search_across_domains(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.index([
        _chunk("m1", domain="metadata", breadcrumb="revenue account"),
        _chunk("d1", domain="documents", breadcrumb="revenue policy"),
    ])
    # Full-scope search (no domain filter)
    results = writer.keyword_search("revenue", top_k=10, domain_id=None)
    ids = {r.chunk_id for r in results}
    assert "m1" in ids
    assert "d1" in ids


def test_search_domain_scoped(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.index([
        _chunk("m1", domain="metadata", breadcrumb="revenue account"),
        _chunk("d1", domain="documents", breadcrumb="revenue policy"),
    ])
    results = writer.keyword_search("revenue", top_k=10, domain_id="metadata")
    ids = {r.chunk_id for r in results}
    assert "m1" in ids
    assert "d1" not in ids


def test_search_empty_domain_returns_empty(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    # No index for "missing" domain
    results = writer.keyword_search("revenue", top_k=5, domain_id="missing")
    assert results == []


def test_search_empty_query_returns_empty(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.index([_chunk("c1")])
    # Empty query
    results = writer.keyword_search("", top_k=5, domain_id="metadata")
    assert results == []


def test_wipe_index(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.index([_chunk("c1")])
    writer.wipe_index("metadata")
    assert not (tmp_path / "whoosh" / "metadata").exists()
    # Search after wipe returns empty
    results = writer.keyword_search("revenue", top_k=5, domain_id="metadata")
    assert results == []


def test_wipe_nonexistent_domain_no_error(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    writer.wipe_index("nonexistent")  # should not raise


def test_is_ready_when_dir_exists(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    assert writer.is_ready is True


def test_update_document_idempotent(tmp_path):
    writer = LuceneIndexWriter(index_dir=tmp_path / "whoosh")
    chunk = _chunk("c1", breadcrumb="unique revenue account breadcrumb")
    writer.index([chunk])
    writer.index([chunk])  # index same chunk again
    results = writer.keyword_search("unique", top_k=10, domain_id="metadata")
    # Should not have duplicates
    ids = [r.chunk_id for r in results]
    assert ids.count("c1") == 1


def test_open_existing_index(tmp_path):
    base = tmp_path / "whoosh"
    writer = LuceneIndexWriter(index_dir=base)
    writer.index([_chunk("c1")])
    # Create a second writer pointing to the same dir — should open existing
    writer2 = LuceneIndexWriter(index_dir=base)
    results = writer2.keyword_search("revenue", top_k=5, domain_id="metadata")
    assert any(r.chunk_id == "c1" for r in results)
