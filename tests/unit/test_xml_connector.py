from __future__ import annotations

from pathlib import Path

import pytest

from src.connectors.xml_file import XMLFileConnector
from src.domain.entity_types import EntityTypeRegistry


def _make_connector(xml_path: Path) -> XMLFileConnector:
    reg = EntityTypeRegistry()
    return XMLFileConnector(file_path=xml_path, entity_types=reg)


def test_fetch_all_accounts(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    accounts = [e for e in entities if e.entity_type == "Account" and not e.entity_id.startswith("link_")]
    codes = {e.entity_id for e in accounts}
    assert {"REVENUE", "PROD_REVENUE", "SAAS_REVENUE", "COGS"}.issubset(codes)


def test_account_parent_relationship(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    saas = next(e for e in entities if e.entity_id == "SAAS_REVENUE")
    assert saas.parent_id == "PROD_REVENUE"


def test_account_rels_parent_of(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    saas = next(e for e in entities if e.entity_id == "SAAS_REVENUE")
    rel_types = {r.relation_type for r in saas.relationships}
    assert "PARENT_OF" in rel_types


def test_linked_account_entities(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    linked = [e for e in entities if any(r.relation_type == "LINKED_TO" for r in e.relationships)]
    assert len(linked) >= 1


def test_levels_parsed(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    levels = [e for e in entities if e.entity_type == "Level"]
    assert any(e.entity_id == "CORPORATE" for e in levels)


def test_versions_parsed(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    versions = [e for e in entities if e.entity_type == "Version"]
    actual = next((e for e in versions if e.entity_id == "ACTUAL"), None)
    assert actual is not None
    assert actual.properties.get("start_time") == "2026-01-01"


def test_sheets_parsed(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    sheets = [e for e in entities if e.entity_type == "Sheet"]
    assert any(e.entity_id == "PL_Summary" for e in sheets)


def test_sheet_has_account_relationships(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    pl = next(e for e in entities if e.entity_id == "PL_Summary")
    includes = [r for r in pl.relationships if r.relation_type == "INCLUDES_ACCOUNT"]
    assert len(includes) >= 1


def test_dimensions_parsed(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    dims = [e for e in entities if e.entity_type == "Dimension"]
    assert any(e.entity_id == "Region" for e in dims)


def test_dimvalues_parsed(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    vals = [e for e in entities if e.entity_type == "DimValue"]
    names = {e.entity_id for e in vals}
    assert {"EMEA", "NA"}.issubset(names)


def test_dimvalue_parent_is_dimension(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    emea = next(e for e in entities if e.entity_id == "EMEA")
    assert emea.parent_id == "Region"


def test_connect_missing_file():
    conn = XMLFileConnector(Path("/nonexistent/path.xml"), EntityTypeRegistry())
    with pytest.raises(FileNotFoundError):
        conn.connect()


def test_disconnect_is_noop(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.disconnect()  # should not raise


def test_domain_id_propagated(sample_xml_path):
    conn = XMLFileConnector(sample_xml_path, EntityTypeRegistry(), domain_id="custom")
    conn.connect()
    entities = list(conn.fetch_all())
    assert all(e.domain_id == "custom" for e in entities)


# ── Edge cases — empty-code elements and missing Accounts (covers skipped lines) ─

def _write_xml(tmp_path, content: bytes) -> Path:
    p = tmp_path / "edge.xml"
    p.write_bytes(content)
    return p


def test_no_accounts_section(tmp_path):
    # L47: Accounts element missing → _parse_accounts returns early
    xml = b'<PlanningMetadata><Levels/></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Account" for e in entities)


def test_account_with_empty_code_skipped(tmp_path):
    # L51: Account element with no code attribute is skipped
    xml = b'<PlanningMetadata><Accounts><Account desc="no code"/></Accounts></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Account" for e in entities)


def test_account_attr_elements_parsed(tmp_path):
    # L59-62: Account with <Attr> child elements → properties populated
    xml = b'''<PlanningMetadata>
      <Accounts>
        <Account code="ACC1" desc="Test">
          <Attr name="metric" value="arr"/>
          <Attr name="billing_type" value="monthly"/>
        </Account>
      </Accounts>
    </PlanningMetadata>'''
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    acc = next(e for e in entities if e.entity_id == "ACC1")
    assert acc.properties.get("metric") == "arr"
    assert acc.properties.get("billing_type") == "monthly"


def test_level_with_empty_code_skipped(tmp_path):
    # L95: Level with no code is skipped
    xml = b'<PlanningMetadata><Levels><Level desc="no code"/></Levels></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Level" for e in entities)


def test_version_with_empty_code_skipped(tmp_path):
    # L109: Version with no code is skipped
    xml = b'<PlanningMetadata><Versions><Version desc="no code"/></Versions></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Version" for e in entities)


def test_sheet_with_empty_name_skipped(tmp_path):
    # L128: Sheet with no name is skipped
    xml = b'<PlanningMetadata><Sheets><Sheet desc="no name"/></Sheets></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Sheet" for e in entities)


def test_dimension_with_empty_name_skipped(tmp_path):
    # L157: Dimension with no name is skipped
    xml = b'<PlanningMetadata><Dimensions><Dimension/></Dimensions></PlanningMetadata>'
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "Dimension" for e in entities)


def test_dimvalue_with_empty_name_skipped(tmp_path):
    # L166: DimValue with no name is skipped
    xml = b'''<PlanningMetadata>
      <Dimensions>
        <Dimension name="Region">
          <DimValue value="no name"/>
        </Dimension>
      </Dimensions>
    </PlanningMetadata>'''
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    assert not any(e.entity_type == "DimValue" for e in entities)


# ── Hierarchy enrichment (PR #5) ─────────────────────────────────────────────


def test_account_props_carry_parent_code(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    saas = next(e for e in entities if e.entity_id == "SAAS_REVENUE")
    assert saas.properties.get("parent_code") == "PROD_REVENUE"


def test_account_props_carry_children(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    revenue = next(e for e in entities if e.entity_id == "REVENUE")
    children = revenue.properties.get("children") or []
    assert "PROD_REVENUE" in children


def test_account_props_carry_linked_accounts(sample_xml_path):
    conn = _make_connector(sample_xml_path)
    conn.connect()
    entities = list(conn.fetch_all())
    # Whichever Account has a LINKED_TO peer should now expose it inline.
    candidates = [
        e for e in entities
        if e.entity_type == "Account"
        and not e.entity_id.startswith("link_")
        and e.properties.get("linked_accounts")
    ]
    assert candidates, "Expected at least one account to surface linked_accounts"


def test_children_capped_with_ellipsis(tmp_path):
    # Cap at 10 → an 11th sibling is summarised as "…"
    kids = "".join(f'<Account code="K{i:02d}" desc="kid {i}"/>' for i in range(15))
    xml = (
        b'<PlanningMetadata><Accounts>'
        b'<Account code="ROOT" desc="root">' + kids.encode() + b'</Account>'
        b'</Accounts></PlanningMetadata>'
    )
    conn = XMLFileConnector(_write_xml(tmp_path, xml), EntityTypeRegistry())
    entities = list(conn.fetch_all())
    root = next(e for e in entities if e.entity_id == "ROOT")
    children = root.properties["children"]
    assert len(children) == 11  # 10 kids + ellipsis sentinel
    assert children[-1] == "…"
