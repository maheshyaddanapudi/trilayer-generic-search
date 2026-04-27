from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from src.domain.graph_schema import GraphSchema, NodeLabel, RelationshipDefinition
from src.indexers.graph import GraphIndexWriter
from src.models.core import MetadataChunk, RawEntity, RawRelationship


def _schema():
    return GraphSchema(
        domain_namespace="meta",
        node_labels={
            "Account": NodeLabel("meta_Account", "Account", "code"),
        },
        relationships=[
            RelationshipDefinition("PARENT_OF", "meta_Account", "meta_Account", directed=True),
        ],
    )


def _chunk(cid, domain="metadata"):
    return MetadataChunk(chunk_id=cid, domain_id=domain, entity_id=cid,
                         entity_type="Account", breadcrumb=f"BC {cid}")


def _entity(eid):
    return RawEntity(entity_id=eid, entity_type="Account", domain_id="metadata", name=eid)


def test_index_empty_returns_zero(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.index([]) == 0


def test_index_chunks_merges_nodes(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    count = writer.index([_chunk("c1"), _chunk("c2")])
    assert count == 2
    session = mock_neo4j_driver.session.return_value
    assert session.run.call_count == 2


def test_index_entities(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    count = writer.index_entities([_entity("REVENUE")], _schema())
    assert count == 1


def test_index_entities_skips_unknown_type(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    entity = RawEntity("X", "UnknownType", "metadata", "X")
    count = writer.index_entities([entity], _schema())
    assert count == 0


def test_index_relationships(mock_neo4j_driver):
    entity = _entity("PROD_REVENUE")
    entity.relationships = [
        RawRelationship(source_id="REVENUE", target_id="PROD_REVENUE", relation_type="PARENT_OF"),
    ]
    writer = GraphIndexWriter(mock_neo4j_driver)
    count = writer.index_relationships([entity], _schema())
    assert count == 1


def test_index_relationships_skips_unknown_rel(mock_neo4j_driver):
    entity = _entity("X")
    entity.relationships = [
        RawRelationship("A", "B", "UNKNOWN_REL"),
    ]
    writer = GraphIndexWriter(mock_neo4j_driver)
    count = writer.index_relationships([entity], _schema())
    assert count == 0


def test_get_neighbours_empty_inputs(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.get_neighbours([], ["PARENT_OF"]) == []
    assert writer.get_neighbours(["c1"], []) == []


def test_get_neighbours_returns_chunks(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    session.run.return_value = iter([
        {"chunk_id": "c2", "breadcrumb": "BC c2",
         "entity_id": "c2", "entity_type": "Account", "domain_id": "metadata"},
    ])
    writer = GraphIndexWriter(mock_neo4j_driver)
    result = writer.get_neighbours(["c1"], ["PARENT_OF"])
    assert len(result) == 1
    assert result[0].chunk_id == "c2"


def test_get_ancestors_unknown_type(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    result = writer.get_ancestors("X", "UnknownType", _schema())
    assert result == []


def test_get_ancestors_returns_names(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    session.run.return_value = iter([{"name": "REVENUE"}, {"name": "PROD_REVENUE"}])
    writer = GraphIndexWriter(mock_neo4j_driver)
    result = writer.get_ancestors("SAAS_REVENUE", "Account", _schema())
    assert "REVENUE" in result


def test_cypher_query_returns_dicts(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    session.run.return_value = iter([{"name": "REVENUE"}])
    writer = GraphIndexWriter(mock_neo4j_driver)
    result = writer.cypher_query("MATCH (n) RETURN n.code AS name")
    assert result == [{"name": "REVENUE"}]


def test_cypher_query_with_params(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    session.run.return_value = iter([])
    writer = GraphIndexWriter(mock_neo4j_driver)
    writer.cypher_query("MATCH (n) WHERE n.code = $code RETURN n", {"code": "X"})
    session.run.assert_called_once()


def test_index_relationships_skips_entity_type_not_in_schema(mock_neo4j_driver):
    # L66: entity.entity_type not in schema.node_labels → continue
    entity = RawEntity("X", "UnknownEntityType", "metadata", "X")
    entity.relationships = [
        RawRelationship("X", "Y", "PARENT_OF"),
    ]
    writer = GraphIndexWriter(mock_neo4j_driver)
    count = writer.index_relationships([entity], _schema())
    assert count == 0


def test_close_calls_driver(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    writer.close()
    mock_neo4j_driver.close.assert_called_once()


def test_is_ready_true(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.is_ready is True


def test_is_ready_false_on_exception(mock_neo4j_driver):
    mock_neo4j_driver.session.side_effect = Exception("down")
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.is_ready is False


def test_get_ancestors_batch_empty_input_short_circuits(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.get_ancestors_batch([], "Account", _schema()) == {}
    # No driver call made for empty input.
    mock_neo4j_driver.session.assert_not_called()


def test_get_ancestors_batch_unknown_type_short_circuits(mock_neo4j_driver):
    writer = GraphIndexWriter(mock_neo4j_driver)
    assert writer.get_ancestors_batch(["A"], "UnknownType", _schema()) == {}


def test_get_ancestors_batch_groups_results_by_source(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    session.run.return_value = iter([
        {"source": "SAAS_REVENUE", "ancestor": "PROD_REVENUE"},
        {"source": "SAAS_REVENUE", "ancestor": "REVENUE"},
        {"source": "COGS",         "ancestor": "ROOT"},
    ])
    writer = GraphIndexWriter(mock_neo4j_driver)
    out = writer.get_ancestors_batch(["SAAS_REVENUE", "COGS"], "Account", _schema())
    assert out["SAAS_REVENUE"] == ["PROD_REVENUE", "REVENUE"]
    assert out["COGS"] == ["ROOT"]
    # Single round-trip — exactly one session.run() call.
    session.run.assert_called_once()


def test_bootstrap_schema_issues_constraints_for_each_label(mock_neo4j_driver):
    session = mock_neo4j_driver.session.return_value
    writer = GraphIndexWriter(mock_neo4j_driver)
    n_ok = writer.bootstrap_schema(_schema(), "metadata")
    # 1 label constraint + 1 chunk constraint + 1 breadcrumb index = 3 statements
    assert n_ok == 3
    statements = [c.args[0] for c in session.run.call_args_list]
    # Label constraint
    assert any("FOR (n:meta_Account)" in s and "REQUIRE n.code IS UNIQUE" in s
               for s in statements)
    # Chunk constraint
    assert any("FOR (n:Chunk_metadata)" in s and "REQUIRE n.chunk_id IS UNIQUE" in s
               for s in statements)
    # Breadcrumb index
    assert any("CREATE INDEX IF NOT EXISTS" in s and "ON (n.breadcrumb)" in s
               for s in statements)
