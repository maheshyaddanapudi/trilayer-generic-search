from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_document_upload_and_search():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_document_delete_clears_vector():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_document_section_level_search():
    pytest.skip("requires live Docker services (neo4j + postgres)")


def test_document_cross_domain_search():
    pytest.skip("requires live Docker services (neo4j + postgres)")
