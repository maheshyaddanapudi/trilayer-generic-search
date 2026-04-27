"""LLM client factory.

Selects the concrete :class:`LLMClient` implementation based on
``settings.llm_provider`` and the requested *role* (``"intent"`` or
``"synthesis"``). This keeps provider-selection logic out of
:mod:`src.main` and makes it trivial to add more providers later.
"""
from __future__ import annotations

from typing import Literal

from src.config import Settings
from src.llm.client import AnthropicLLMClient, LLMClient
from src.llm.ollama_client import OllamaLLMClient

Role = Literal["intent", "synthesis"]


def build_llm_client(settings: Settings, role: Role) -> LLMClient:
    """Build an LLM client for the given role.

    Parameters
    ----------
    settings:
        Application settings (reads ``llm_provider`` plus provider-specific keys).
    role:
        Either ``"intent"`` (used by the intent parser) or ``"synthesis"``
        (used by the response synthesizer). Each role can be backed by a
        different model size to balance cost and quality.
    """
    provider = settings.llm_provider
    if provider == "ollama":
        model = (
            settings.ollama_intent_model if role == "intent"
            else settings.ollama_synthesis_model
        )
        return OllamaLLMClient(
            base_url=settings.ollama_base_url,
            model=model,
            timeout_s=settings.ollama_request_timeout_s,
        )

    if provider == "anthropic":
        model = (
            settings.intent_model if role == "intent"
            else settings.synthesis_model
        )
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            default_model=model,
        )

    raise ValueError(f"Unknown LLM provider: {provider!r}")
