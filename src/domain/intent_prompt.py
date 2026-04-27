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
        return (
            "You are a search intent classifier.\n\n"
            f"Entity types in this domain:\n{entity_lines}\n\n"
            f"Synonym expansion map:\n{synonym_lines}\n\n"
            f"Query type examples:\n{example_lines}\n\n"
            "Return JSON with keys: query_type (LOOKUP|TRAVERSAL|DISCOVERY), "
            "expanded_query (string), entity_hint (string|null), confidence (0-1), "
            "cypher_hints (list of strings)."
        )
