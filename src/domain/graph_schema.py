from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TraversalDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    BOTH = "both"


@dataclass
class NodeLabel:
    label: str
    entity_type: str
    id_property: str
    searchable_properties: list[str] = field(default_factory=list)


@dataclass
class RelationshipDefinition:
    relation_type: str
    source_label: str
    target_label: str
    directed: bool = True
    inverse_name: str | None = None


@dataclass
class TraversalRule:
    relation_type: str
    direction: TraversalDirection
    max_depth: int = 1
    use_for_boost: bool = False


@dataclass
class GraphSchema:
    domain_namespace: str
    node_labels: dict[str, NodeLabel] = field(default_factory=dict)
    relationships: list[RelationshipDefinition] = field(default_factory=list)
    traversal_rules: list[TraversalRule] = field(default_factory=list)
    boost_edges: list[str] = field(default_factory=list)

    def node_label_for(self, entity_type: str) -> str:
        return self.node_labels[entity_type].label

    def boost_relation_types(self) -> list[str]:
        return self.boost_edges
