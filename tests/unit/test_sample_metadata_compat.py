"""Guard against schema regressions in data/sample_metadata.xml.

The shipped sample XML must be parseable by ``XMLFileConnector``. Historically
the file was checked in with lowercase / hyphenated tags
(``<accounts>``, ``<account-attribute>`` …) which the connector silently
ignores, producing zero entities at index time. This test fails fast if that
ever happens again.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from plugins.metadata.plugin import METADATA_ENTITY_TYPES
from src.connectors.xml_file import XMLFileConnector

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_XML = REPO_ROOT / "data" / "sample_metadata.xml"


@pytest.fixture
def connector() -> XMLFileConnector:
    if not SAMPLE_XML.exists():
        pytest.skip(f"sample metadata file missing: {SAMPLE_XML}")
    return XMLFileConnector(file_path=SAMPLE_XML, entity_types=METADATA_ENTITY_TYPES)


def test_sample_xml_parses_to_nonzero_entities(connector: XMLFileConnector) -> None:
    entities = list(connector.fetch_all())
    assert len(entities) > 0, (
        "data/sample_metadata.xml produced 0 entities — the schema is likely "
        "out of sync with XMLFileConnector (must use CapWords tags: "
        "<Accounts>, <Account>, <Attr>, <Levels>, <Versions>, <Sheets>, "
        "<Dimensions>)."
    )


def test_sample_xml_contains_core_account_codes(connector: XMLFileConnector) -> None:
    """Smoke-check a few well-known account codes from the canonical sample."""
    entities = list(connector.fetch_all())
    account_codes = {e.entity_id for e in entities if e.entity_type == "Account"}

    expected = {"REVENUE", "PROD_REVENUE", "SAAS_REVENUE", "COGS"}
    missing = expected - account_codes
    assert not missing, (
        f"sample_metadata.xml is missing expected accounts: {missing}. "
        f"Found accounts: {sorted(account_codes)[:10]}…"
    )


def test_sample_xml_emits_levels_versions_sheets_dimensions(connector: XMLFileConnector) -> None:
    entities = list(connector.fetch_all())
    types_seen = {e.entity_type for e in entities}
    for required in ("Account", "Level", "Version", "Sheet", "Dimension", "DimValue"):
        assert required in types_seen, (
            f"sample_metadata.xml emits no '{required}' entities — section "
            f"likely missing or mis-tagged. Saw: {sorted(types_seen)}"
        )
