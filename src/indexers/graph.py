from __future__ import annotations

import logging
from typing import Any

from src.domain.graph_schema import GraphSchema
from src.indexers.base import IndexWriter
from src.models.core import MetadataChunk, RawEntity, SearchResult

log = logging.getLogger(__name__)


class GraphIndexWriter(IndexWriter):
    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def index(self, chunks: list[MetadataChunk]) -> int:
        if not chunks:
            return 0
        count = 0
        with self._driver.session() as session:
            for chunk in chunks:
                label = f"Chunk_{chunk.domain_id}"
                props = {
                    "chunk_id": chunk.chunk_id,
                    "entity_id": chunk.entity_id,
                    "entity_type": chunk.entity_type,
                    "breadcrumb": chunk.breadcrumb,
                    "domain_id": chunk.domain_id,
                }
                session.run(
                    f"MERGE (n:{label} {{chunk_id: $chunk_id}}) SET n += $props",
                    chunk_id=chunk.chunk_id, props=props,
                )
                count += 1
        return count

    def index_entities(self, entities: list[RawEntity], schema: GraphSchema) -> int:
        count = 0
        with self._driver.session() as session:
            for entity in entities:
                if entity.entity_type not in schema.node_labels:
                    continue
                node_def = schema.node_labels[entity.entity_type]
                props: dict[str, Any] = {node_def.id_property: entity.entity_id, **entity.properties}
                if entity.name:
                    props["name"] = entity.name
                session.run(
                    f"MERGE (n:{node_def.label} {{{node_def.id_property}: $id}}) SET n += $props",
                    id=entity.entity_id, props=props,
                )
                count += 1
        return count

    def index_relationships(self, entities: list[RawEntity], schema: GraphSchema) -> int:
        rel_types = {r.relation_type for r in schema.relationships}
        count = 0
        with self._driver.session() as session:
            for entity in entities:
                for rel in entity.relationships:
                    if rel.relation_type not in rel_types:
                        continue
                    rel_def = next(r for r in schema.relationships if r.relation_type == rel.relation_type)
                    src_node = schema.node_labels.get(entity.entity_type)
                    if not src_node:
                        continue
                    cypher = (
                        f"MATCH (a:{rel_def.source_label} {{{src_node.id_property}: $src}}) "
                        f"MATCH (b:{rel_def.target_label}) WHERE b.code = $tgt OR b.name = $tgt "
                        f"MERGE (a)-[:{rel.relation_type}]->(b)"
                    )
                    session.run(cypher, src=entity.entity_id, tgt=rel.target_id)
                    count += 1
        return count

    def get_neighbours(self, chunk_ids: list[str], relation_types: list[str],
                       depth: int = 1) -> list[MetadataChunk]:
        if not chunk_ids or not relation_types:
            return []
        rel_pattern = "|".join(relation_types)
        result: list[MetadataChunk] = []
        with self._driver.session() as session:
            cypher = (
                f"MATCH (n)-[:{rel_pattern}*1..{depth}]-(m) "
                "WHERE n.chunk_id IN $ids AND m.chunk_id IS NOT NULL "
                "RETURN DISTINCT m.chunk_id AS chunk_id, m.breadcrumb AS breadcrumb, "
                "m.entity_id AS entity_id, m.entity_type AS entity_type, m.domain_id AS domain_id"
            )
            records = session.run(cypher, ids=chunk_ids)
            for rec in records:
                result.append(MetadataChunk(
                    chunk_id=rec["chunk_id"],
                    domain_id=rec.get("domain_id") or "",
                    entity_id=rec.get("entity_id") or "",
                    entity_type=rec.get("entity_type") or "",
                    breadcrumb=rec.get("breadcrumb") or "",
                ))
        return result

    def get_ancestors(self, entity_id: str, entity_type: str,
                      schema: GraphSchema, depth: int = 3) -> list[str]:
        if entity_type not in schema.node_labels:
            return []
        node_def = schema.node_labels[entity_type]
        with self._driver.session() as session:
            cypher = (
                f"MATCH (n:{node_def.label} {{{node_def.id_property}: $id}})"
                f"<-[:PARENT_OF*1..{depth}]-(a:{node_def.label}) "
                f"RETURN a.{node_def.id_property} AS name"
            )
            records = session.run(cypher, id=entity_id)
            return [rec["name"] for rec in records]

    def get_ancestors_batch(self, entity_ids: list[str], entity_type: str,
                            schema: GraphSchema, depth: int = 3) -> dict[str, list[str]]:
        """Batched ancestor lookup. Returns ``{entity_id: [ancestor_id, ...]}``.

        Issues a single Cypher round-trip via ``UNWIND`` instead of one per
        entity. Empty input or unknown ``entity_type`` short-circuits to ``{}``.
        """
        if not entity_ids or entity_type not in schema.node_labels:
            return {}
        node_def = schema.node_labels[entity_type]
        cypher = (
            f"UNWIND $ids AS id "
            f"MATCH (n:{node_def.label} {{{node_def.id_property}: id}})"
            f"<-[:PARENT_OF*1..{depth}]-(a:{node_def.label}) "
            f"RETURN id AS source, a.{node_def.id_property} AS ancestor"
        )
        out: dict[str, list[str]] = {}
        with self._driver.session() as session:
            for rec in session.run(cypher, ids=entity_ids):
                out.setdefault(rec["source"], []).append(rec["ancestor"])
        return out

    def bootstrap_schema(self, schema: GraphSchema, domain_id: str) -> int:
        """Pre-warm the Neo4j catalog with idempotent DDL.

        Issues ``CREATE CONSTRAINT IF NOT EXISTS`` for every label's id property
        plus the per-domain ``Chunk_<domain_id>`` table, and a non-unique index
        on chunk breadcrumbs. This eliminates the cold-cache ``01N50``
        (label-not-exists) and ``01N52`` (property-not-exists) GqlStatusObject
        warnings that the driver re-emits at WARNING level for every query.

        Per-statement exceptions are swallowed and logged so a partially-broken
        catalog does not fail startup. Returns the number of statements that
        ran successfully.
        """
        statements: list[str] = []
        for node_def in schema.node_labels.values():
            statements.append(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{node_def.label}) "
                f"REQUIRE n.{node_def.id_property} IS UNIQUE"
            )
        chunk_label = f"Chunk_{domain_id}"
        statements.append(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{chunk_label}) "
            f"REQUIRE n.chunk_id IS UNIQUE"
        )
        statements.append(
            f"CREATE INDEX IF NOT EXISTS FOR (n:{chunk_label}) ON (n.breadcrumb)"
        )
        ok = 0
        with self._driver.session() as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                    ok += 1
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("bootstrap_schema: %s — %s", stmt, exc)
        return ok

    def cypher_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            records = session.run(cypher, **(params or {}))
            return [dict(rec) for rec in records]

    def close(self) -> None:
        self._driver.close()

    @property
    def is_ready(self) -> bool:
        try:
            with self._driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False
