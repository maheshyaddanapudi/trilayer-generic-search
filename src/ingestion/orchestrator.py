from __future__ import annotations

import logging
import time

from src.domain.config import DomainConfig
from src.domain.registry import DomainRegistry
from src.indexers.graph import GraphIndexWriter
from src.indexers.lucene import LuceneIndexWriter
from src.indexers.vector import VectorIndexWriter
from src.ingestion.breadcrumb_gen import BreadcrumbGenerator
from src.models.core import IngestionMode, IngestionResult, MetadataChunk, RawEntity

log = logging.getLogger(__name__)


class IngestionOrchestrator:
    def __init__(
        self,
        registry: DomainRegistry,
        vector_writer: VectorIndexWriter,
        lucene_writer: LuceneIndexWriter,
        graph_writer: GraphIndexWriter,
        breadcrumb_gen: BreadcrumbGenerator,
    ) -> None:
        self._registry = registry
        self._vector = vector_writer
        self._lucene = lucene_writer
        self._graph = graph_writer
        self._breadcrumb_gen = breadcrumb_gen

    def ingest_domain(self, domain_id: str, mode: IngestionMode) -> IngestionResult:
        t0 = time.monotonic()
        config = self._registry.get(domain_id)

        if mode == IngestionMode.FULL:
            self._clear_domain(domain_id)

        entities: list[RawEntity] = []
        chunks: list[MetadataChunk] = []
        errors: list[str] = []

        config.connector.connect()
        try:
            for entity in config.connector.fetch_all():
                entities.append(entity)
        finally:
            config.connector.disconnect()

        # Build the parent_of map up-front so the breadcrumb generator can
        # walk lineage in-memory instead of issuing one Cypher round-trip per
        # entity. The graph is empty at ingest-time anyway (entities have not
        # been written yet), so the in-memory walk is also correct on first run.
        parent_of: dict[str, str | None] = {e.entity_id: e.parent_id for e in entities}

        for entity in entities:
            try:
                chunk = self._breadcrumb_gen.generate(entity, config, parent_chain=parent_of)
                chunks.append(chunk)
            except Exception as exc:
                log.warning("Breadcrumb gen failed for %s: %s", entity.entity_id, exc)
                errors.append(str(exc))

        graph_nodes = 0
        if chunks:
            self._fan_out(chunks)
            try:
                graph_nodes = self._graph.index_entities(entities, config.graph_schema)
                self._graph.index_relationships(entities, config.graph_schema)
            except Exception as exc:
                log.warning("Graph entity/relationship indexing failed: %s", exc)
                errors.append(str(exc))

        return IngestionResult(
            domain_id=domain_id,
            entities_ingested=len(entities),
            chunks_indexed=len(chunks),
            graph_nodes=graph_nodes,
            duration_ms=(time.monotonic() - t0) * 1000,
            errors=errors,
        )

    def _clear_domain(self, domain_id: str) -> None:
        try:
            self._vector.clear_domain(domain_id)
        except Exception as exc:
            log.warning("Vector clear failed for %s: %s", domain_id, exc)
        self._lucene.wipe_index(domain_id)

    def _fan_out(self, chunks: list[MetadataChunk]) -> None:
        try:
            self._vector.index(chunks)
        except Exception as exc:
            log.warning("Vector index failed: %s", exc)
        try:
            self._lucene.index(chunks)
        except Exception as exc:
            log.warning("Lucene index failed: %s", exc)
        try:
            self._graph.index(chunks)
        except Exception as exc:
            log.warning("Graph index failed: %s", exc)
