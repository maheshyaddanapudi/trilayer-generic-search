from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

from lxml import etree

from src.domain.connector import SourceConnector
from src.domain.entity_types import EntityTypeRegistry
from src.models.core import RawEntity, RawRelationship

log = logging.getLogger(__name__)


class XMLFileConnector(SourceConnector):
    supports_incremental = False

    def __init__(self, file_path: Path, entity_types: EntityTypeRegistry,
                 domain_id: str = "metadata") -> None:
        self._path = file_path
        self._entity_types = entity_types
        self._domain_id = domain_id

    def connect(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Metadata file not found: {self._path}")

    def disconnect(self) -> None:
        pass

    def fetch_all(self) -> Iterator[RawEntity]:
        tree = etree.parse(str(self._path))
        root = tree.getroot()
        yield from self._parse_accounts(root)
        yield from self._parse_levels(root)
        yield from self._parse_versions(root)
        yield from self._parse_sheets(root)
        yield from self._parse_dimensions(root)

    # ── Accounts ────────────────────────────────────────────────────────────

    # Cap how many siblings/links we inline into the breadcrumb so a single
    # high-degree node (e.g. a top-level rollup with 200 children) does not
    # blow past ``max_total_length``. Anything beyond the cap is summarised
    # as ``"…"``.
    _BREADCRUMB_NEIGHBOUR_CAP = 10

    def _parse_accounts(self, root: etree._Element) -> Iterator[RawEntity]:
        accounts_el = root.find(".//Accounts")
        if accounts_el is None:
            return

        # First pass: build child + linked maps so each Account carries its
        # immediate hierarchy info inline. This lets the breadcrumb (and
        # therefore the embedding) include "parent=…", "children=…" and
        # "linked=…" without a follow-up graph query.
        children_of: dict[str, list[str]] = {}
        linked_to: dict[str, list[str]] = {}

        for acct in accounts_el.findall(".//Account"):
            code = acct.get("code", "")
            if not code:
                continue
            parent_el = acct.getparent()
            if parent_el is not None and parent_el.tag == "Account":
                p = parent_el.get("code", "")
                if p:
                    children_of.setdefault(p, []).append(code)

        for link_el in root.findall(".//LinkedAccountGroup"):
            members = [m.get("code", "") for m in link_el.findall("Member") if m.get("code")]
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    linked_to.setdefault(a, []).append(b)
                    linked_to.setdefault(b, []).append(a)

        # Second pass: emit the Account entities with hierarchy injected.
        for acct in accounts_el.findall(".//Account"):
            code = acct.get("code", "")
            if not code:
                continue
            desc = acct.get("desc", "")
            acct_type = acct.get("type", "")
            parent_el = acct.getparent()
            parent_code = parent_el.get("code") if parent_el is not None and parent_el.tag == "Account" else None

            props: dict = {"type": acct_type}
            for attr in acct.findall("Attr"):
                key = attr.get("name", "")
                val = attr.get("value", attr.text or "")
                if key:
                    props[key] = val
            if parent_code:
                props["parent_code"] = parent_code
            kids = children_of.get(code, [])
            if kids:
                props["children"] = self._cap_neighbours(kids)
            links = linked_to.get(code, [])
            if links:
                props["linked_accounts"] = self._cap_neighbours(links)

            rels: list[RawRelationship] = []
            if parent_code:
                rels.append(RawRelationship(source_id=parent_code, target_id=code,
                                            relation_type="PARENT_OF"))

            yield RawEntity(
                entity_id=code, entity_type="Account",
                domain_id=self._domain_id, name=code, description=desc,
                properties=props, parent_id=parent_code, relationships=rels,
            )

        # Linked pairs (synthetic entities used purely as relationship carriers).
        for link_el in root.findall(".//LinkedAccountGroup"):
            members = [m.get("code", "") for m in link_el.findall("Member") if m.get("code")]
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    yield RawEntity(
                        entity_id=f"link_{a}_{b}", entity_type="Account",
                        domain_id=self._domain_id, name=f"{a}-{b}",
                        description=f"Linked: {a} and {b}",
                        properties={},
                        relationships=[RawRelationship(source_id=a, target_id=b,
                                                       relation_type="LINKED_TO")],
                    )

    @classmethod
    def _cap_neighbours(cls, items: list[str]) -> list[str]:
        if len(items) <= cls._BREADCRUMB_NEIGHBOUR_CAP:
            return items
        return items[: cls._BREADCRUMB_NEIGHBOUR_CAP] + ["…"]

    # ── Levels ───────────────────────────────────────────────────────────────

    def _parse_levels(self, root: etree._Element) -> Iterator[RawEntity]:
        for el in root.findall(".//Level"):
            code = el.get("code", "")
            if not code:
                continue
            yield RawEntity(
                entity_id=code, entity_type="Level",
                domain_id=self._domain_id, name=code,
                description=el.get("desc", ""),
                properties={},
            )

    # ── Versions ─────────────────────────────────────────────────────────────

    def _parse_versions(self, root: etree._Element) -> Iterator[RawEntity]:
        for el in root.findall(".//Version"):
            code = el.get("code", "")
            if not code:
                continue
            props: dict = {}
            for attr_name in ("start_time", "end_time", "type"):
                val = el.get(attr_name)
                if val:
                    props[attr_name] = val
            yield RawEntity(
                entity_id=code, entity_type="Version",
                domain_id=self._domain_id, name=code,
                description=el.get("desc", ""),
                properties=props,
            )

    # ── Sheets ───────────────────────────────────────────────────────────────

    def _parse_sheets(self, root: etree._Element) -> Iterator[RawEntity]:
        for el in root.findall(".//Sheet"):
            name = el.get("name", "")
            if not name:
                continue
            rels: list[RawRelationship] = []
            for acct_el in el.findall(".//Account"):
                code = acct_el.get("code", "")
                if code:
                    rels.append(RawRelationship(source_id=name, target_id=code,
                                                relation_type="INCLUDES_ACCOUNT"))
            version = el.get("version", "")
            if version:
                rels.append(RawRelationship(source_id=name, target_id=version,
                                            relation_type="USES_VERSION"))
            level = el.get("level", "")
            if level:
                rels.append(RawRelationship(source_id=name, target_id=level,
                                            relation_type="USES_LEVEL"))
            yield RawEntity(
                entity_id=name, entity_type="Sheet",
                domain_id=self._domain_id, name=name,
                description=el.get("desc", ""),
                properties={"type": el.get("type", "")},
                relationships=rels,
            )

    # ── Dimensions ───────────────────────────────────────────────────────────

    def _parse_dimensions(self, root: etree._Element) -> Iterator[RawEntity]:
        for dim_el in root.findall(".//Dimension"):
            dim_name = dim_el.get("name", "")
            if not dim_name:
                continue
            yield RawEntity(
                entity_id=dim_name, entity_type="Dimension",
                domain_id=self._domain_id, name=dim_name, description="",
                properties={},
            )
            for val_el in dim_el.findall(".//DimValue"):
                val_name = val_el.get("name", "")
                if not val_name:
                    continue
                yield RawEntity(
                    entity_id=val_name, entity_type="DimValue",
                    domain_id=self._domain_id, name=val_name,
                    description=val_el.get("value", ""),
                    properties={"dimension": dim_name, "value": val_el.get("value", "")},
                    parent_id=dim_name,
                    relationships=[RawRelationship(source_id=dim_name, target_id=val_name,
                                                   relation_type="HAS_VALUE")],
                )
