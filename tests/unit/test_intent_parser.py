from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.domain.intent_prompt import IntentPromptConfig
from src.llm.intent_parser import IntentParser, _heuristic_fallback


# ── Heuristic fallback ────────────────────────────────────────────────────────

def test_heuristic_all_caps_lookup():
    intent = _heuristic_fallback("SAAS_REVENUE")
    assert intent.query_type == "LOOKUP"
    assert intent.confidence == 0.0


def test_heuristic_traversal_keywords():
    for q in ["children of REVENUE", "parent of X", "members of dimension",
               "rolls up to OPEX", "ancestors of COGS"]:
        intent = _heuristic_fallback(q)
        assert intent.query_type == "TRAVERSAL", f"Expected TRAVERSAL for: {q}"


def test_heuristic_discovery_default():
    intent = _heuristic_fallback("recurring revenue accounts")
    assert intent.query_type == "DISCOVERY"


def test_heuristic_short_caps_not_lookup():
    # "AB" has only 2 chars after first → does not match [A-Z][A-Z0-9_]{2,}
    intent = _heuristic_fallback("AB revenue")
    assert intent.query_type == "DISCOVERY"


# ── IntentParser (LLM path) ───────────────────────────────────────────────────

def _make_parser(llm_response: str) -> IntentParser:
    llm = MagicMock()
    llm.complete.return_value = llm_response
    cfg = IntentPromptConfig(
        entity_type_descriptions={"Account": "accounts"},
        synonym_expansion_map={},
        query_type_examples={},
    )
    return IntentParser(llm, cfg)


def test_parser_llm_success_high_confidence():
    parser = _make_parser(
        '{"query_type": "LOOKUP", "expanded_query": "SAAS_REVENUE", '
        '"entity_hint": "Account", "confidence": 0.95, "cypher_hints": ["MATCH (n)"]}'
    )
    intent = parser.parse("SAAS_REVENUE")
    assert intent.query_type == "LOOKUP"
    assert intent.confidence == pytest.approx(0.95)
    assert intent.entity_hint == "Account"
    assert "MATCH (n)" in intent.cypher_hints


def test_parser_low_confidence_uses_heuristic():
    parser = _make_parser(
        '{"query_type": "DISCOVERY", "expanded_query": "x", "confidence": 0.3}'
    )
    intent = parser.parse("SAAS_REVENUE")
    # Heuristic kicks in: SAAS_REVENUE is ALL_CAPS → LOOKUP
    assert intent.query_type == "LOOKUP"
    assert intent.confidence == 0.0


def test_parser_llm_exception_uses_heuristic():
    llm = MagicMock()
    llm.complete.side_effect = RuntimeError("timeout")
    cfg = IntentPromptConfig()
    parser = IntentParser(llm, cfg)
    intent = parser.parse("children of REVENUE")
    assert intent.query_type == "TRAVERSAL"


def test_parser_malformed_json_uses_heuristic():
    parser = _make_parser("not json at all {{")
    intent = parser.parse("show revenue accounts")
    assert intent.query_type == "DISCOVERY"


def test_parser_json_embedded_in_text():
    parser = _make_parser(
        'Sure! Here is the result: {"query_type": "TRAVERSAL", '
        '"expanded_query": "children REVENUE", "confidence": 0.85, "cypher_hints": []}'
    )
    intent = parser.parse("children of REVENUE")
    assert intent.query_type == "TRAVERSAL"


def test_parser_missing_fields_use_defaults():
    parser = _make_parser('{"query_type": "DISCOVERY", "confidence": 0.9}')
    intent = parser.parse("revenue")
    assert intent.expanded_query == "revenue"  # falls back to query
    assert intent.cypher_hints == []


def test_parser_embedded_invalid_json_object_uses_heuristic():
    # L68-69: regex finds {…} but json.loads still fails
    parser = _make_parser("Result: {invalid: not json at all!!!}")
    intent = parser.parse("show revenue accounts")
    assert intent.query_type == "DISCOVERY"
