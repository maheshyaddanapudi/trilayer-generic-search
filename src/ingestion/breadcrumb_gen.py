from __future__ import annotations

import logging

from src.domain.breadcrumb import BreadcrumbContext, BreadcrumbTemplate
from src.domain.config import DomainConfig
from src.domain.graph_schema import GraphSchema
from src.indexers.graph import GraphIndexWriter
from src.models.core import MetadataChunk, RawEntity

log = logging.getLogger(__name__)


class BreadcrumbGenerator:
    def __init__(self, graph_writer: GraphIndexWriter | None = None) -> None:
        self._graph = graph_writer

    def generate(
        self,
        entity: RawEntity,
        domain_config: DomainConfig,
        parent_chain: dict[str, str | None] | None = None,
    ) -> MetadataChunk:
        context = self._build_context(entity, domain_config, parent_chain)
        breadcrumb = domain_config.breadcrumb_template.generate(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            name=entity.name,
            description=entity.description,
            properties=entity.properties,
            context=context,
        )
        return MetadataChunk(
            chunk_id=f"{domain_config.domain_id}_{entity.entity_id}",
            domain_id=domain_config.domain_id,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            breadcrumb=breadcrumb,
            properties=entity.properties,
        )

    def _lineage_depth(self, domain_config: DomainConfig) -> int:
        tpl = domain_config.breadcrumb_template
        return tpl._lineage_depth if hasattr(tpl, "_lineage_depth") else 2

    def _walk_parent_chain(
        self,
        entity: RawEntity,
        parent_chain: dict[str, str | None],
        max_depth: int,
    ) -> list[str]:
        """In-memory ancestor walk via the pre-built ``{child: parent}`` map.

        Stops at ``max_depth``, on missing parent, or on a cycle. Returns the
        chain ordered nearest-ancestor → root, mirroring the order that
        ``get_ancestors`` produces for the graph path.
        """
        lineage: list[str] = []
        seen: set[str] = {entity.entity_id}
        current = parent_chain.get(entity.entity_id) or entity.parent_id
        while current and len(lineage) < max_depth and current not in seen:
            lineage.append(current)
            seen.add(current)
            current = parent_chain.get(current)
        return lineage

    def _build_context(
        self,
        entity: RawEntity,
        domain_config: DomainConfig,
        parent_chain: dict[str, str | None] | None,
    ) -> BreadcrumbContext:
        lineage: list[str] = []
        if parent_chain is not None:
            lineage = self._walk_parent_chain(
                entity, parent_chain, self._lineage_depth(domain_config),
            )
        elif entity.parent_id and self._graph:
            try:
                lineage = self._graph.get_ancestors(
                    entity.entity_id, entity.entity_type,
                    domain_config.graph_schema,
                    depth=self._lineage_depth(domain_config),
                )
            except Exception as exc:
                log.debug("Could not fetch ancestors for %s: %s", entity.entity_id, exc)
        if not lineage and entity.parent_id:
            lineage = [entity.parent_id]

        return BreadcrumbContext(
            lineage=lineage,
            domain_display=domain_config.display_name,
        )
