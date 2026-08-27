from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.domain.registry import DomainRegistry
from src.ingestion.orchestrator import IngestionOrchestrator
from src.models.core import IngestionMode, RawEntity


def _make_orchestrator(entities=None):
    registry = DomainRegistry()

    mock_config = MagicMock()
    mock_config.domain_id = "metadata"
    mock_config.graph_schema = MagicMock()

    mock_connector = MagicMock()
    mock_connector.fetch_all.return_value = iter(entities or [])
    mock_config.connector = mock_connector

    registry.register(mock_config)

    vector = MagicMock()
    vector.clear_domain.return_value = 0
    lucene = MagicMock()
    graph = MagicMock()
    graph.index_entities.return_value = 3
    graph.index_relationships.return_value = 2

    breadcrumb_gen = MagicMock()
    breadcrumb_gen.generate.side_effect = lambda entity, cfg, parent_chain=None: MagicMock(
        chunk_id=f"metadata_{entity.entity_id}",
        domain_id="metadata", entity_id=entity.entity_id,
        entity_type=entity.entity_type, breadcrumb="BC",
    )

    orch = IngestionOrchestrator(registry, vector, lucene, graph, breadcrumb_gen)
    return orch, registry, vector, lucene, graph, breadcrumb_gen


def _raw(eid):
    return RawEntity(entity_id=eid, entity_type="Account",
                     domain_id="metadata", name=eid)


def test_full_mode_clears_before_index():
    orch, _, vector, lucene, _, _ = _make_orchestrator([_raw("REVENUE")])
    orch.ingest_domain("metadata", IngestionMode.FULL)
    vector.clear_domain.assert_called_once_with("metadata")
    lucene.wipe_index.assert_called_once_with("metadata")


def test_incremental_mode_does_not_clear():
    orch, _, vector, lucene, _, _ = _make_orchestrator([_raw("REVENUE")])
    orch.ingest_domain("metadata", IngestionMode.INCREMENTAL)
    vector.clear_domain.assert_not_called()
    lucene.wipe_index.assert_not_called()


def test_result_counts():
    orch, _, _, _, _, _ = _make_orchestrator([_raw("A"), _raw("B")])
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert result.entities_ingested == 2
    assert result.chunks_indexed == 2
    assert result.domain_id == "metadata"


def test_fan_out_calls_all_three_writers():
    orch, _, vector, lucene, graph, _ = _make_orchestrator([_raw("A")])
    orch.ingest_domain("metadata", IngestionMode.FULL)
    vector.index.assert_called_once()
    lucene.index.assert_called_once()
    graph.index.assert_called_once()


def test_vector_failure_does_not_stop_ingestion():
    orch, _, vector, lucene, graph, _ = _make_orchestrator([_raw("A")])
    vector.index.side_effect = Exception("vector down")
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    # Lucene and graph still called
    lucene.index.assert_called_once()
    graph.index.assert_called_once()
    assert result.entities_ingested == 1


def test_lucene_failure_continues():
    orch, _, vector, lucene, graph, _ = _make_orchestrator([_raw("A")])
    lucene.index.side_effect = Exception("lucene down")
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    graph.index.assert_called_once()
    assert result.entities_ingested == 1


def test_graph_index_failure_recorded_in_errors():
    orch, _, vector, lucene, graph, _ = _make_orchestrator([_raw("A")])
    graph.index_entities.side_effect = Exception("graph down")
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert len(result.errors) >= 1


def test_breadcrumb_failure_recorded():
    orch, _, _, _, _, bg = _make_orchestrator([_raw("A")])
    bg.generate.side_effect = Exception("bc fail")
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert result.chunks_indexed == 0
    assert len(result.errors) >= 1


def test_vector_clear_failure_continues():
    orch, _, vector, _, _, _ = _make_orchestrator([_raw("A")])
    vector.clear_domain.side_effect = Exception("clear fail")
    # Should not raise
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert result is not None


def test_duration_positive():
    orch, _, _, _, _, _ = _make_orchestrator([_raw("A")])
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert result.duration_ms >= 0


def test_empty_domain_no_crash():
    orch, _, _, _, _, _ = _make_orchestrator([])
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    assert result.entities_ingested == 0
    assert result.chunks_indexed == 0


def test_graph_index_chunk_failure_continues():
    # L93-94: graph.index(chunks) raises → except branch + warning log
    orch, _, vector, lucene, graph, _ = _make_orchestrator([_raw("A")])
    graph.index.side_effect = Exception("graph chunk index down")
    result = orch.ingest_domain("metadata", IngestionMode.FULL)
    vector.index.assert_called_once()
    lucene.index.assert_called_once()
    assert result.entities_ingested == 1
