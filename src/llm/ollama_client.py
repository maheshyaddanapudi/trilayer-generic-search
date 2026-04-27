"""Ollama LLM client.

Talks to a locally-running Ollama server (``http://host:11434``) via its
``/api/chat`` endpoint. Implements the same ``LLMClient.complete`` contract
as :class:`AnthropicLLMClient` so it can be used interchangeably by
:class:`IntentParser` and :class:`Synthesizer`.

Streaming is intentionally disabled to keep the synchronous ``complete()``
signature aligned with the Anthropic implementation.
"""
from __future__ import annotations

import logging
import time

import httpx

from src.llm.client import LLMClient

log = logging.getLogger(__name__)


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 180.0,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        log.info("OllamaLLMClient initialised: model=%s base_url=%s", model, self._base_url)

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        url = f"{self._base_url}/api/chat"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = httpx.post(url, json=payload, timeout=self._timeout_s)
                response.raise_for_status()
                data = response.json()
                # Ollama /api/chat response shape:
                # {"message": {"role": "assistant", "content": "..."}, ...}
                message = data.get("message") or {}
                content = message.get("content", "")
                if not isinstance(content, str):
                    raise RuntimeError(f"Unexpected Ollama response shape: {data!r}")
                return content
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning(
                    "Ollama attempt %d failed: %s; retrying in %ds",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait)

        raise RuntimeError(
            f"Ollama call failed after {self._max_retries} attempts"
        ) from last_exc
