from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import Settings, get_settings, reset_settings
from src.indexers.base import IndexWriter
from src.llm.client import AnthropicLLMClient, LLMClient
from src.llm.synthesizer import Synthesizer
from src.models.core import MetadataChunk, SearchResult
from plugins.metadata.plugin import (
    METADATA_ENTITY_TYPES,
    METADATA_GRAPH_SCHEMA,
    build_metadata_domain,
)
from plugins.documents.plugin import (
    DOCUMENT_ENTITY_TYPES,
    DOCUMENT_GRAPH_SCHEMA,
    build_document_domain,
)


# ── Settings / config.py ──────────────────────────────────────────────────────

def test_settings_defaults():
    s = Settings()
    assert s.neo4j_uri == "bolt://localhost:7687"
    assert s.embedding_dimension == 384
    assert s.rrf_k == 60
    assert s.graph_boost_factor == 1.5


def test_get_settings_singleton():
    reset_settings()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_reset_settings_creates_new_instance():
    reset_settings()
    s1 = get_settings()
    reset_settings()
    s2 = get_settings()
    assert s1 is not s2


# ── IndexWriter base (indexers/base.py) ───────────────────────────────────────

def test_index_writer_is_abstract():
    with pytest.raises(TypeError):
        IndexWriter()  # type: ignore[abstract]


def test_concrete_index_writer_can_be_instantiated():
    class ConcreteWriter(IndexWriter):
        def index(self, chunks):
            return len(chunks)

        @property
        def is_ready(self):
            return True

    w = ConcreteWriter()
    chunk = MetadataChunk(chunk_id="c1", domain_id="m", entity_id="c1",
                          entity_type="X", breadcrumb="BC")
    assert w.index([chunk]) == 1
    assert w.is_ready is True


# ── LLMClient / AnthropicLLMClient ────────────────────────────────────────────

def test_llm_client_is_abstract():
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def _make_anthropic_mock():
    """Inject a fake anthropic module into sys.modules and return the mock client."""
    mock_anthropic_module = MagicMock()
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    return mock_anthropic_module, mock_client


def test_anthropic_client_success():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="answer text")]
    mock_anthropic_module, mock_client = _make_anthropic_mock()
    mock_client.messages.create.return_value = mock_response

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        client = AnthropicLLMClient(api_key="sk-test")
        result = client.complete("Hello", max_tokens=128)

    assert result == "answer text"


def test_anthropic_client_with_system_prompt():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_anthropic_module, mock_client = _make_anthropic_mock()
    mock_client.messages.create.return_value = mock_response

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        client = AnthropicLLMClient(api_key="sk-test")
        client.complete("Hi", system="You are helpful")
        call_kwargs = mock_client.messages.create.call_args[1]

    assert "system" in call_kwargs
    assert call_kwargs["system"] == "You are helpful"


def test_anthropic_client_no_system_not_in_kwargs():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_anthropic_module, mock_client = _make_anthropic_mock()
    mock_client.messages.create.return_value = mock_response

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
        client = AnthropicLLMClient(api_key="sk-test")
        client.complete("Hi")
        call_kwargs = mock_client.messages.create.call_args[1]

    assert "system" not in call_kwargs


def test_anthropic_client_retry_then_succeed():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="success")]
    mock_anthropic_module, mock_client = _make_anthropic_mock()
    mock_client.messages.create.side_effect = [Exception("transient"), mock_response]

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}), \
         patch("src.llm.client.time") as mock_time:
        client = AnthropicLLMClient(api_key="sk-test", max_retries=3)
        result = client.complete("Hi")

    assert result == "success"
    assert mock_time.sleep.call_count == 1


def test_anthropic_client_all_retries_fail():
    mock_anthropic_module, mock_client = _make_anthropic_mock()
    mock_client.messages.create.side_effect = Exception("always fails")

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}), \
         patch("src.llm.client.time") as mock_time:
        client = AnthropicLLMClient(api_key="sk-test", max_retries=3)
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            client.complete("Hi")

    assert mock_time.sleep.call_count == 3


# ── Synthesizer ───────────────────────────────────────────────────────────────

def _result(cid, source="vector"):
    return SearchResult(
        chunk_id=cid, score=1.0, breadcrumb=f"BC {cid}",
        entity_id=cid, entity_type="Account",
        domain_id="metadata", rank=0, source=source,
    )


def test_synthesizer_empty_results():
    llm = MagicMock()
    synth = Synthesizer(llm)
    result = synth.synthesize("query", [])
    assert result == ""
    llm.complete.assert_not_called()


def test_synthesizer_returns_llm_output():
    llm = MagicMock()
    llm.complete.return_value = "Revenue is tracked in SAAS_REVENUE."
    synth = Synthesizer(llm)
    result = synth.synthesize("revenue", [_result("c1")])
    assert result == "Revenue is tracked in SAAS_REVENUE."


def test_synthesizer_llm_failure_returns_empty():
    llm = MagicMock()
    llm.complete.side_effect = Exception("LLM down")
    synth = Synthesizer(llm)
    result = synth.synthesize("revenue", [_result("c1")])
    assert result == ""


def test_synthesizer_domain_hint_included():
    llm = MagicMock()
    llm.complete.return_value = "ok"
    synth = Synthesizer(llm)
    synth.synthesize("revenue", [_result("c1")], domain_hint="metadata")
    prompt = llm.complete.call_args[0][0]
    assert "metadata" in prompt


# ── Metadata plugin ───────────────────────────────────────────────────────────

def test_metadata_domain_id():
    cfg = build_metadata_domain(Path("/tmp/sample.xml"))
    assert cfg.domain_id == "metadata"


def test_metadata_display_name():
    cfg = build_metadata_domain(Path("/tmp/sample.xml"))
    assert "Financial Planning" in cfg.display_name


def test_metadata_entity_types_count():
    assert len(list(METADATA_ENTITY_TYPES.names())) == 6


def test_metadata_entity_types_names():
    names = set(METADATA_ENTITY_TYPES.names())
    assert {"Account", "Level", "Version", "Sheet", "Dimension", "DimValue"} == names


def test_metadata_graph_schema_namespace():
    assert METADATA_GRAPH_SCHEMA.domain_namespace == "meta"


def test_metadata_graph_schema_rel_count():
    assert len(METADATA_GRAPH_SCHEMA.relationships) == 6


def test_metadata_graph_schema_node_labels():
    assert "Account" in METADATA_GRAPH_SCHEMA.node_labels
    assert METADATA_GRAPH_SCHEMA.node_labels["Account"].label == "meta_Account"


def test_metadata_trigger_full_reindex_on_startup():
    cfg = build_metadata_domain(Path("/tmp/sample.xml"))
    assert cfg.trigger_config.full_reindex_on_startup is True


def test_metadata_boost_factor():
    cfg = build_metadata_domain(Path("/tmp/sample.xml"))
    assert cfg.graph_boost_factor == 1.5


def test_metadata_rrf_k():
    cfg = build_metadata_domain(Path("/tmp/sample.xml"))
    assert cfg.rrf_k == 60


# ── Document plugin ───────────────────────────────────────────────────────────

def test_document_domain_id():
    cfg = build_document_domain(Path("/tmp"))
    assert cfg.domain_id == "documents"


def test_document_display_name():
    cfg = build_document_domain(Path("/tmp"))
    assert "Document" in cfg.display_name or "Policy" in cfg.display_name


def test_document_entity_types_count():
    assert len(list(DOCUMENT_ENTITY_TYPES.names())) == 2


def test_document_entity_types_names():
    names = set(DOCUMENT_ENTITY_TYPES.names())
    assert {"Document", "Section"} == names


def test_document_graph_schema_namespace():
    assert DOCUMENT_GRAPH_SCHEMA.domain_namespace == "doc"


def test_document_graph_schema_rel_count():
    assert len(DOCUMENT_GRAPH_SCHEMA.relationships) == 3


def test_document_graph_schema_node_labels():
    assert "Document" in DOCUMENT_GRAPH_SCHEMA.node_labels
    assert DOCUMENT_GRAPH_SCHEMA.node_labels["Document"].label == "doc_Document"


def test_document_trigger_no_startup_reindex():
    cfg = build_document_domain(Path("/tmp"))
    assert cfg.trigger_config.full_reindex_on_startup is False


def test_document_boost_factor():
    cfg = build_document_domain(Path("/tmp"))
    assert cfg.graph_boost_factor == 1.4
