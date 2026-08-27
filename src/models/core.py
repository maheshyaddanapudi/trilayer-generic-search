from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict


class IngestionMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class RawRelationship:
    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawEntity:
    entity_id: str
    entity_type: str
    domain_id: str
    name: str
    description: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    relationships: list[RawRelationship] = field(default_factory=list)
    ingested_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MetadataChunk:
    chunk_id: str
    domain_id: str
    entity_id: str
    entity_type: str
    breadcrumb: str
    embedding: list[float] | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    breadcrumb: str
    entity_id: str
    entity_type: str
    domain_id: str
    rank: int = 0
    source: str = ""


@dataclass
class ParsedIntent:
    query_type: str                          # LOOKUP | TRAVERSAL | DISCOVERY
    expanded_query: str
    entity_hint: str | None = None
    scope_filters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    cypher_hints: list[str] = field(default_factory=list)


class SearchState(TypedDict, total=False):
    query: str
    domain: str | None
    top_k: int
    intent: ParsedIntent
    vector_results: list[SearchResult]
    lucene_results: list[SearchResult]
    graph_results: list[SearchResult]
    final_results: list[SearchResult]
    synthesis: str
    latency_ms: float


@dataclass
class IngestionResult:
    domain_id: str
    entities_ingested: int
    chunks_indexed: int
    graph_nodes: int
    duration_ms: float
    errors: list[str] = field(default_factory=list)
