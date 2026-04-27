from __future__ import annotations

import logging

from src.llm.client import LLMClient
from src.models.core import SearchResult

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a precise search assistant. Answer ONLY using the provided breadcrumbs. "
    "Do not invent facts not present in the breadcrumbs. "
    "Cite entity names exactly as they appear."
)


class Synthesizer:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def synthesize(self, query: str, results: list[SearchResult],
                   domain_hint: str = "") -> str:
        if not results:
            return ""
        context = "\n".join(
            f"{i + 1}. [{r.source}] {r.breadcrumb}" for i, r in enumerate(results)
        )
        prompt = (
            f"Query: {query}\n\n"
            f"Domain: {domain_hint or 'all'}\n\n"
            f"Breadcrumbs:\n{context}\n\n"
            "Provide a concise, grounded answer citing relevant breadcrumbs."
        )
        try:
            return self._llm.complete(prompt, system=_SYSTEM, max_tokens=512, temperature=0.0)
        except Exception as exc:
            log.warning("Synthesis failed: %s; returning empty synthesis", exc)
            return ""
