from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntentPromptConfig:
    entity_type_descriptions: dict[str, str] = field(default_factory=dict)
    synonym_expansion_map: dict[str, list[str]] = field(default_factory=dict)
    query_type_examples: dict[str, list[str]] = field(default_factory=dict)
    cypher_hint_patterns: dict[str, str] = field(default_factory=dict)
    grounding_format_description: str = ""

    def build_system_prompt(self) -> str:
        entity_lines = "\n".join(
            f"  - {k}: {v}" for k, v in self.entity_type_descriptions.items()
        )
        synonym_lines = "\n".join(
            f"  {k}: {', '.join(vs)}" for k, vs in self.synonym_expansion_map.items()
        )
        example_lines = "\n".join(
            f"  {qt}: {exs}" for qt, exs in self.query_type_examples.items()
        )
        cypher_lines = (
            "\n".join(f"  {name}: {pattern}"
                      for name, pattern in self.cypher_hint_patterns.items())
            if self.cypher_hint_patterns else "  (none — return empty list)"
        )
        return (
            "You are a search intent classifier. "
            "Analyze the query and return a single JSON object.\n\n"
            f"Entity types:\n{entity_lines}\n\n"
            f"Synonym expansion:\n{synonym_lines}\n\n"
            f"Query type examples:\n{example_lines}\n\n"
            "Cypher hint patterns — use ONLY these exact label names "
            "and relationship types when generating cypher_hints:\n"
            f"{cypher_lines}\n\n"
            "Rules:\n"
            "  - expanded_query: 3-8 keyword phrase, NOT a full sentence\n"
            "  - cypher_hints: use ONLY label names from the patterns above; "
            "return [] if unsure\n"
            "  - confidence: 0.9+ if entity clearly identified, "
            "0.7-0.9 for reasonable match, <0.7 if very uncertain\n\n"
            "Return ONLY the JSON object below — no prose, "
            "no markdown fences, no explanation:\n"
            "{\n"
            '  "query_type": "LOOKUP|TRAVERSAL|DISCOVERY",\n'
            '  "expanded_query": "<3-8 keyword phrase>",\n'
            '  "entity_hint": "<entity name/code or null>",\n'
            '  "confidence": <0.0-1.0>,\n'
            '  "cypher_hints": []\n'
            "}"
        )
