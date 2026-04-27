from __future__ import annotations

from unittest.mock import MagicMock

from src.ingestion.breadcrumb_gen import BreadcrumbGenerator
from src.models.core import RawEntity
from plugins.metadata.plugin import build_metadata_domain
from plugins.documents.plugin import build_document_domain
from pathlib import Path


def _meta_domain():
    return build_metadata_domain(Path("/tmp/sample.xml"))


def _doc_domain():
    return build_document_domain(Path("/tmp/uploads"))


def _entity(eid, etype="Account", parent_id=None, props=None):
    return RawEntity(
        entity_id=eid, entity_type=etype, domain_id="metadata",
        name=eid, description=f"Desc of {eid}",
        properties=props or {}, parent_id=parent_id,
    )


def test_generate_chunk_id_format():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    assert chunk.chunk_id == "metadata_REVENUE"


def test_generate_sets_domain_and_type():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("ACTUAL", etype="Version")
    chunk = gen.generate(entity, _meta_domain())
    assert chunk.domain_id == "metadata"
    assert chunk.entity_type == "Version"


def test_breadcrumb_contains_entity_id():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("SAAS_REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    assert "SAAS_REVENUE" in chunk.breadcrumb


def test_breadcrumb_uses_graph_ancestors():
    mock_graph = MagicMock()
    mock_graph.get_ancestors.return_value = ["PROD_REVENUE", "REVENUE"]
    gen = BreadcrumbGenerator(graph_writer=mock_graph)
    entity = _entity("SAAS_REVENUE", parent_id="PROD_REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    assert "PROD_REVENUE" in chunk.breadcrumb


def test_breadcrumb_falls_back_to_parent_id_when_no_graph():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("SAAS_REVENUE", parent_id="PROD_REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    assert "PROD_REVENUE" in chunk.breadcrumb


def test_graph_ancestor_exception_uses_parent_id():
    mock_graph = MagicMock()
    mock_graph.get_ancestors.side_effect = Exception("graph down")
    gen = BreadcrumbGenerator(graph_writer=mock_graph)
    entity = _entity("SAAS_REVENUE", parent_id="PROD_REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    # Should not raise; breadcrumb still produced
    assert chunk.breadcrumb


def test_no_parent_uses_domain_display():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("REVENUE")
    chunk = gen.generate(entity, _meta_domain())
    assert "Metadata" in chunk.breadcrumb or "REVENUE" in chunk.breadcrumb


def test_document_section_breadcrumb():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = RawEntity(
        entity_id="sec1", entity_type="Section", domain_id="documents",
        name="CapEx Policy §4.2", description="CFO sign-off required",
        properties={"page_number": 8, "owner": "CFO Office"},
        parent_id="doc1",
    )
    chunk = gen.generate(entity, _doc_domain())
    assert "CapEx Policy §4.2" in chunk.breadcrumb


def test_parent_chain_walks_in_memory_skipping_graph():
    # When parent_chain is supplied, the graph writer must NOT be consulted —
    # the lineage walk happens entirely in memory.
    mock_graph = MagicMock()
    gen = BreadcrumbGenerator(graph_writer=mock_graph)
    entity = _entity("SAAS_REVENUE", parent_id="PROD_REVENUE")
    parent_chain = {
        "SAAS_REVENUE": "PROD_REVENUE",
        "PROD_REVENUE": "REVENUE",
        "REVENUE": None,
    }
    chunk = gen.generate(entity, _meta_domain(), parent_chain=parent_chain)
    assert "PROD_REVENUE" in chunk.breadcrumb
    mock_graph.get_ancestors.assert_not_called()


def test_parent_chain_handles_cycle_gracefully():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("A", parent_id="B")
    # Self-cycle: A→B→A→…
    parent_chain = {"A": "B", "B": "A"}
    chunk = gen.generate(entity, _meta_domain(), parent_chain=parent_chain)
    # Must not infinite-loop and must still produce a breadcrumb.
    assert chunk.breadcrumb


def test_parent_chain_empty_falls_back_to_parent_id():
    # An orphan whose parent isn't in the chain still gets parent_id appended.
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("ORPHAN", parent_id="GHOST_PARENT")
    chunk = gen.generate(entity, _meta_domain(), parent_chain={"ORPHAN": None})
    assert "GHOST_PARENT" in chunk.breadcrumb


# ── Hierarchy attribute slots (PR #5) ────────────────────────────────────────


def test_account_breadcrumb_surfaces_parent_children_linked():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity(
        "PROD_REVENUE", parent_id="REVENUE",
        props={
            "parent_code":      "REVENUE",
            "children":         ["SAAS_REVENUE", "LICENSE_REVENUE"],
            "linked_accounts":  ["SUBSCRIPTION_REVENUE"],
        },
    )
    chunk = gen.generate(entity, _meta_domain())
    bc = chunk.breadcrumb
    assert "parent=REVENUE" in bc
    assert "children=" in bc and "SAAS_REVENUE" in bc and "LICENSE_REVENUE" in bc
    assert "linked=" in bc and "SUBSCRIPTION_REVENUE" in bc


def test_account_breadcrumb_omits_hierarchy_when_absent():
    gen = BreadcrumbGenerator(graph_writer=None)
    entity = _entity("STANDALONE")  # no parent_code / children / linked
    chunk = gen.generate(entity, _meta_domain())
    bc = chunk.breadcrumb
    assert "parent=" not in bc
    assert "children=" not in bc
    assert "linked=" not in bc
