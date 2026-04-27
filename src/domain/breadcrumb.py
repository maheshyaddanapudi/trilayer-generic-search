from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BreadcrumbSlot:
    field_path: str          # dot-path into RawEntity: "properties.metric"
    label: str | None = None  # prefix like "metric=" or None for bare value


@dataclass
class BreadcrumbContext:
    lineage: list[str] = field(default_factory=list)   # ancestor names, nearest first
    domain_display: str = "Metadata"


class BreadcrumbTemplate(ABC):
    @abstractmethod
    def generate(self, entity_id: str, entity_type: str, name: str,
                 description: str, properties: dict[str, Any],
                 context: BreadcrumbContext) -> str:
        ...


def _resolve(path: str, properties: dict[str, Any]) -> Any:
    parts = path.split(".")
    obj: Any = {"properties": properties}
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


class TemplateBreadcrumbTemplate(BreadcrumbTemplate):
    def __init__(
        self,
        identity_slot: BreadcrumbSlot,
        description_slot: BreadcrumbSlot,
        attribute_slots: list[BreadcrumbSlot],
        lineage_depth: int = 2,
        separator: str = " | ",
        max_total_length: int = 512,
    ) -> None:
        self._identity = identity_slot
        self._description = description_slot
        self._attributes = attribute_slots
        self._lineage_depth = lineage_depth
        self._separator = separator
        self._max_length = max_total_length

    def generate(self, entity_id: str, entity_type: str, name: str,
                 description: str, properties: dict[str, Any],
                 context: BreadcrumbContext) -> str:
        sep = self._separator

        identity = self._resolve_slot(self._identity, entity_id, name, description, properties) or entity_id
        lineage = self._build_lineage(context)
        desc = self._resolve_slot(self._description, entity_id, name, description, properties) or ""
        attrs = self._build_attrs(properties)

        parts = [identity, entity_type]
        if lineage:
            parts.append(lineage)
        if desc:
            parts.append(desc)
        if attrs:
            parts.append(attrs)

        result = sep.join(parts)
        if len(result) <= self._max_length:
            return result

        # Truncate: drop attrs right-to-left, then truncate desc
        parts_truncated = [identity, entity_type]
        if lineage:
            parts_truncated.append(lineage)

        base = sep.join(parts_truncated)
        remaining = self._max_length - len(base) - len(sep)
        if remaining > 0 and desc:
            parts_truncated.append(desc[:remaining])
        return sep.join(parts_truncated)

    def _resolve_slot(self, slot: BreadcrumbSlot, entity_id: str, name: str,
                      description: str, properties: dict[str, Any]) -> str | None:
        path = slot.field_path
        if path == "entity_id":
            val = entity_id
        elif path == "name":
            val = name
        elif path == "description":
            val = description
        else:
            val = _resolve(path, properties)
        if val is None:
            return None
        text = str(val) if not isinstance(val, list) else ", ".join(str(v) for v in val)
        if slot.label:
            return f"{slot.label}{text}"
        return text

    def _build_lineage(self, context: BreadcrumbContext) -> str:
        ancestors = context.lineage[: self._lineage_depth]
        if not ancestors:
            return context.domain_display
        return "parent:" + " > ".join(ancestors)

    def _build_attrs(self, properties: dict[str, Any]) -> str:
        parts: list[str] = []
        for slot in self._attributes:
            resolved = _resolve(slot.field_path, properties)
            if resolved is None:
                continue
            text = str(resolved) if not isinstance(resolved, list) else ", ".join(str(v) for v in resolved)
            if slot.label:
                parts.append(f"{slot.label}{text}")
            else:
                parts.append(text)
        return "; ".join(parts)
