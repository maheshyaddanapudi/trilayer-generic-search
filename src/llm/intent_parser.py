from __future__ import annotations

import json
import logging
import re

from src.domain.intent_prompt import IntentPromptConfig
from src.llm.client import LLMClient
from src.models.core import ParsedIntent

log = logging.getLogger(__name__)

_TRAVERSAL_KEYWORDS = frozenset([
    "children of", "parent of", "rolls up to", "in sheet", "contains",
    "members of", "ancestors", "descendants", "hierarchy", "under", "above",
    "sections of", "what's in", "what is in",
])
_CAPS_RE = re.compile(r'\b[A-Z][A-Z0-9_]{2,}\b')


def _heuristic_fallback(query: str) -> ParsedIntent:
    q_lower = query.lower()
    if any(kw in q_lower for kw in _TRAVERSAL_KEYWORDS):
        return ParsedIntent(query_type="TRAVERSAL", expanded_query=query, confidence=0.0)
    if _CAPS_RE.search(query):
        return ParsedIntent(query_type="LOOKUP", expanded_query=query, confidence=0.0)
    return ParsedIntent(query_type="DISCOVERY", expanded_query=query, confidence=0.0)


class IntentParser:
    def __init__(self, llm: LLMClient, intent_config: IntentPromptConfig) -> None:
        self._llm = llm
        self._config = intent_config
        self._system = intent_config.build_system_prompt()

    def parse(self, query: str) -> ParsedIntent:
        try:
            raw = self._llm.complete(query, system=self._system, max_tokens=200, temperature=0.0)
            data = self._extract_json(raw)
            confidence = float(data.get("confidence", 0.0))
            if confidence < 0.7:
                log.debug("LLM confidence %.2f < 0.7; using heuristic", confidence)
                return _heuristic_fallback(query)
            return ParsedIntent(
                query_type=data.get("query_type", "DISCOVERY").upper(),
                expanded_query=data.get("expanded_query", query),
                entity_hint=data.get("entity_hint"),
                confidence=confidence,
                cypher_hints=data.get("cypher_hints", []),
            )
        except Exception as exc:
            log.warning("Intent LLM failed (%s); falling back to heuristic", exc)
            return _heuristic_fallback(query)

    @staticmethod
    def _extract_json(text: str) -> dict:
        # Try raw JSON first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON block in response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}
