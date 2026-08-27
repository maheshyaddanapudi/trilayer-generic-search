from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from src.domain.registry import DomainRegistry


# ── Reset singletons between tests ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    DomainRegistry.reset()
    yield
    DomainRegistry.reset()


# ── Minimal sample XML ────────────────────────────────────────────────────────

SAMPLE_XML = b"""<?xml version="1.0"?>
<PlanningMetadata>
  <Accounts>
    <Account code="REVENUE" desc="Total Revenue" type="standard">
      <Account code="PROD_REVENUE" desc="Product Revenue" type="standard">
        <Account code="SAAS_REVENUE" desc="SaaS ARR" type="cube"/>
      </Account>
    </Account>
    <Account code="COGS" desc="Cost of Goods Sold" type="standard"/>
  </Accounts>
  <LinkedAccountGroups>
    <LinkedAccountGroup>
      <Member code="REVENUE"/>
      <Member code="COGS"/>
    </LinkedAccountGroup>
  </LinkedAccountGroups>
  <Levels>
    <Level code="CORPORATE" desc="Corporate consolidated"/>
  </Levels>
  <Versions>
    <Version code="ACTUAL" desc="Actuals" start_time="2026-01-01" end_time="2026-03-31"/>
  </Versions>
  <Sheets>
    <Sheet name="PL_Summary" desc="P&amp;L sheet" type="standard" version="ACTUAL" level="CORPORATE">
      <Account code="REVENUE"/>
      <Account code="COGS"/>
    </Sheet>
  </Sheets>
  <Dimensions>
    <Dimension name="Region">
      <DimValue name="EMEA" value="Europe Middle East Africa"/>
      <DimValue name="NA" value="North America"/>
    </Dimension>
  </Dimensions>
</PlanningMetadata>
"""


@pytest.fixture
def sample_xml_path(tmp_path: Path) -> Path:
    p = tmp_path / "sample_metadata.xml"
    p.write_bytes(SAMPLE_XML)
    return p


# ── Mock PGVector connection ──────────────────────────────────────────────────

@pytest.fixture
def mock_pg_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = lambda s: cursor
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.rowcount = 0
    cursor.fetchall.return_value = []
    conn.cursor.return_value = cursor
    return conn


# ── Mock Neo4j driver ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_neo4j_driver():
    driver = MagicMock()
    session = MagicMock()
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    session.run.return_value = iter([])
    driver.session.return_value = session
    return driver


# ── Mock sentence-transformers model ─────────────────────────────────────────

@pytest.fixture
def mock_model():
    model = MagicMock()
    model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
    return model


# ── Mock LLM client ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.complete.return_value = (
        '{"query_type": "DISCOVERY", "expanded_query": "revenue accounts", '
        '"entity_hint": "Account", "confidence": 0.92, "cypher_hints": []}'
    )
    return llm
