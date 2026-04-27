from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    LIST = "list"


@dataclass
class PropertyDefinition:
    name: str
    field_type: FieldType
    required: bool = False


@dataclass
class EntityTypeDefinition:
    name: str
    id_field: str
    display_field: str
    description_field: str
    properties: list[PropertyDefinition] = field(default_factory=list)
    parent_type: str | None = None
    searchable_fields: list[str] = field(default_factory=list)


class EntityTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, EntityTypeDefinition] = {}

    def register(self, definition: EntityTypeDefinition) -> None:
        self._types[definition.name] = definition

    def get(self, name: str) -> EntityTypeDefinition:
        if name not in self._types:
            raise KeyError(f"Entity type '{name}' not registered")
        return self._types[name]

    def all(self) -> list[EntityTypeDefinition]:
        return list(self._types.values())

    def names(self) -> list[str]:
        return list(self._types.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._types
