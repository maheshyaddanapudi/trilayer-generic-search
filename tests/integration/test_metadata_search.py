from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_metadata_full_pipeline():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_metadata_incremental_ingest():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_metadata_search_by_account_name():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_metadata_graph_traversal():
    pytest.skip("requires live Docker services (neo4j + postgres)")
