from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str = "", max_tokens: int = 512,
                 temperature: float = 0.0) -> str: ...


class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: str, default_model: str = "claude-haiku-4-5-20251001",
                 max_retries: int = 3) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = default_model
        self._max_retries = max_retries

    def complete(self, prompt: str, system: str = "", max_tokens: int = 512,
                 temperature: float = 0.0) -> str:
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.messages.create(**kwargs)
                return response.content[0].text
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning("LLM attempt %d failed: %s; retrying in %ds", attempt + 1, exc, wait)
                time.sleep(wait)

        raise RuntimeError(f"LLM call failed after {self._max_retries} attempts") from last_exc
