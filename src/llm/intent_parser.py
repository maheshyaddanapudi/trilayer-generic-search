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
    def __init__(self, llm: LLMClient,
                 configs: "dict[str, IntentPromptConfig] | IntentPromptConfig") -> None:
        self._llm = llm
        # Accept either a single config (legacy) or a domain→config mapping.
        if isinstance(configs, dict):
            self._configs: dict[str, IntentPromptConfig] = configs
        else:
            self._configs = {"_default": configs}
        self._merged_system = self._build_merged_prompt(self._configs)

    # ── System prompt builders ────────────────────────────────────────────────

    @staticmethod
    def _build_merged_prompt(configs: "dict[str, IntentPromptConfig]") -> str:
        merged_entities: dict[str, str] = {}
        merged_synonyms: dict[str, list[str]] = {}
        merged_examples: dict[str, list[str]] = {}
        merged_cypher: dict[str, str] = {}
        for cfg in configs.values():
            merged_entities.update(cfg.entity_type_descriptions)
            merged_synonyms.update(cfg.synonym_expansion_map)
            merged_examples.update(cfg.query_type_examples)
            merged_cypher.update(cfg.cypher_hint_patterns)
        from src.domain.intent_prompt import IntentPromptConfig as _IPC
        base = _IPC(
            entity_type_descriptions=merged_entities,
            synonym_expansion_map=merged_synonyms,
            query_type_examples=merged_examples,
            cypher_hint_patterns=merged_cypher,
        ).build_system_prompt()
        # Append cross-domain guidance so the model knows spanning queries
        # are expected and should not be penalised with low confidence.
        return (
            base
            + "\n\nThis is a MULTI-DOMAIN search. Queries may reference entity "
            "types from different domains simultaneously (e.g. an Account and a "
            "Document in the same question). For such cross-domain queries, "
            "classify as DISCOVERY and set confidence >= 0.7."
        )

    def _system_for(self, domain: "str | None") -> str:
        if domain and domain in self._configs:
            return self._configs[domain].build_system_prompt()
        return self._merged_system

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, query: str, domain: "str | None" = None) -> ParsedIntent:
        system = self._system_for(domain)
        try:
            raw = self._llm.complete(query, system=system, max_tokens=600, temperature=0.0)
            log.info("Intent LLM raw response (domain=%s): %s", domain, raw)
            data = self._extract_json(raw)
            confidence = float(data.get("confidence", 0.0))
            # Cross-domain queries span multiple entity namespaces so Haiku
            # naturally scores them lower; accept a slightly relaxed threshold.
            threshold = 0.6 if domain is None else 0.7
            if confidence < threshold:
                log.info("LLM confidence %.2f < %.1f; using heuristic fallback",
                         confidence, threshold)
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
        text = text.strip()
        # Strip markdown code fences that some models emit despite instructions
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text.strip())
            text = text.strip()
        # Try raw JSON first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON block embedded in prose
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}
