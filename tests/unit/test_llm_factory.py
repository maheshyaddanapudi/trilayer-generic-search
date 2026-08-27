from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.config import Settings
from src.llm.client import AnthropicLLMClient
from src.llm.factory import build_llm_client
from src.llm.ollama_client import OllamaLLMClient


def _settings(**overrides) -> Settings:
    """Construct a Settings without reading the environment / .env file."""
    base = dict(
        llm_provider="anthropic",
        anthropic_api_key="sk-test",
        intent_model="claude-intent",
        synthesis_model="claude-synth",
        ollama_base_url="http://x:11434",
        ollama_intent_model="ollama-intent",
        ollama_synthesis_model="ollama-synth",
        ollama_request_timeout_s=42.0,
    )
    base.update(overrides)
    return Settings(**base)


# ── Anthropic branch ──────────────────────────────────────────────────────────

def test_factory_anthropic_intent():
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = MagicMock()
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        client = build_llm_client(_settings(llm_provider="anthropic"), role="intent")

    assert isinstance(client, AnthropicLLMClient)
    assert client._model == "claude-intent"
    assert client._max_retries == 3


def test_factory_anthropic_synthesis():
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = MagicMock()
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        client = build_llm_client(_settings(llm_provider="anthropic"), role="synthesis")

    assert isinstance(client, AnthropicLLMClient)
    assert client._model == "claude-synth"


# ── Ollama branch ─────────────────────────────────────────────────────────────

def test_factory_ollama_intent():
    client = build_llm_client(_settings(llm_provider="ollama"), role="intent")

    assert isinstance(client, OllamaLLMClient)
    assert client._model == "ollama-intent"
    assert client._base_url == "http://x:11434"
    assert client._timeout_s == 42.0


def test_factory_ollama_synthesis():
    client = build_llm_client(_settings(llm_provider="ollama"), role="synthesis")

    assert isinstance(client, OllamaLLMClient)
    assert client._model == "ollama-synth"


# ── Unknown provider ──────────────────────────────────────────────────────────

def test_factory_unknown_provider_raises():
    settings = _settings(llm_provider="anthropic")
    # Bypass pydantic's Literal validation by setting the attribute directly
    # via __dict__ — pydantic v2 BaseSettings does not validate on assignment
    # by default, but going via __dict__ is the safest path.
    object.__setattr__(settings, "llm_provider", "bogus")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_llm_client(settings, role="intent")
