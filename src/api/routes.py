from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from src.connectors.file_system import SUPPORTED_MIMES
from src.models.core import IngestionMode

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# ── Request / Response Models ─────────────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    domain: Literal["metadata", "documents"] | None = None
    top_k: int = Field(default=10, ge=1, le=20)
    search_mode: Literal["hybrid", "vector", "lucene", "graph"] = "hybrid"


class SearchResultOut(BaseModel):
    chunk_id: str
    score: float
    breadcrumb: str
    entity_id: str
    entity_type: str
    domain_id: str
    rank: int
    source: str


class SearchResponse(BaseModel):
    query: str
    domain: str | None
    results: list[SearchResultOut]
    synthesis: str
    intent: dict
    latency_ms: float


class IndexRequest(BaseModel):
    metadata_file: str | None = None
    metadata_xml: str | None = None


class IndexResponse(BaseModel):
    domain: str
    entities_indexed: int
    chunks_indexed: int
    duration_ms: float


class FileUploadResponse(BaseModel):
    doc_id: str
    title: str
    sections_indexed: int
    vector_docs: int
    lucene_docs: int
    graph_nodes: int
    duration_ms: float
    file_size_bytes: int


class DocumentInfo(BaseModel):
    doc_id: str
    title: str


class DomainHealth(BaseModel):
    """Per-domain health: registered vs. actually queryable.

    A domain is ``registered`` once its plugin is wired into the registry.
    It is ``indexed`` once at least one chunk for that domain exists in the
    vector store. ``chunk_count`` is the exact row count and is reported on
    a best-effort basis (returns 0 if the vector store is down).
    """
    registered: bool
    indexed: bool
    chunk_count: int


class HealthResponse(BaseModel):
    status: str
    neo4j_ok: bool
    vector_ok: bool
    lucene_ok: bool
    # Legacy boolean flags — preserved for backward compatibility.
    # They report *registered* state only; new code should consult the
    # nested ``metadata`` / ``documents`` ``DomainHealth`` objects below.
    metadata_domain: bool
    documents_domain: bool
    metadata: DomainHealth
    documents: DomainHealth
    uptime_seconds: float


# ── Routers ────────────────────────────────────────────────────────────────────

search_router = APIRouter()
index_router = APIRouter()
health_router = APIRouter()

_startup_time = time.monotonic()


# ── Health ─────────────────────────────────────────────────────────────────────

@health_router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    state = request.app.state
    graph_ok = getattr(state, "graph_writer", None) is not None and state.graph_writer.is_ready
    vector_ok = getattr(state, "vector_writer", None) is not None and state.vector_writer.is_ready
    lucene_ok = getattr(state, "lucene_writer", None) is not None and state.lucene_writer.is_ready
    registry = getattr(state, "registry", None)
    meta_registered = registry is not None and "metadata" in registry
    doc_registered = registry is not None and "documents" in registry

    meta_health = _domain_health(state, "metadata", meta_registered)
    doc_health = _domain_health(state, "documents", doc_registered)

    return HealthResponse(
        status="ok",
        neo4j_ok=graph_ok,
        vector_ok=vector_ok,
        lucene_ok=lucene_ok,
        metadata_domain=meta_registered,
        documents_domain=doc_registered,
        metadata=meta_health,
        documents=doc_health,
        uptime_seconds=time.monotonic() - _startup_time,
    )


def _domain_health(state, domain_id: str, registered: bool) -> "DomainHealth":
    """Best-effort per-domain probe that never raises."""
    chunk_count = 0
    if registered:
        vw = getattr(state, "vector_writer", None)
        counter = getattr(vw, "count_domain", None)
        if callable(counter):
            try:
                chunk_count = int(counter(domain_id))
            except Exception:
                chunk_count = 0
    return DomainHealth(
        registered=registered,
        indexed=chunk_count > 0,
        chunk_count=chunk_count,
    )


# ── Search ─────────────────────────────────────────────────────────────────────

@search_router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request) -> SearchResponse:
    orchestrator = _get_orchestrator(request)
    if req.domain:
        registry = request.app.state.registry
        if req.domain not in registry:
            raise HTTPException(status_code=404,
                                detail=f"Domain '{req.domain}' not registered. "
                                       f"Available: {registry.ids()}")
    state = await orchestrator.run(req.query, domain=req.domain, top_k=req.top_k)
    results = [
        SearchResultOut(**{
            "chunk_id": r.chunk_id, "score": r.score, "breadcrumb": r.breadcrumb,
            "entity_id": r.entity_id, "entity_type": r.entity_type,
            "domain_id": r.domain_id, "rank": r.rank, "source": r.source,
        })
        for r in state.get("final_results", [])
    ]
    intent = state.get("intent")
    intent_dict: dict = {}
    if intent:
        intent_dict = {
            "query_type": intent.query_type,
            "expanded_query": intent.expanded_query,
            "entity_hint": intent.entity_hint,
            "confidence": intent.confidence,
        }
    return SearchResponse(
        query=req.query,
        domain=req.domain,
        results=results,
        synthesis=state.get("synthesis", ""),
        intent=intent_dict,
        latency_ms=state.get("latency_ms", 0.0),
    )


# ── Metadata Index ─────────────────────────────────────────────────────────────

@index_router.post("/domains/metadata/index", response_model=IndexResponse)
async def index_metadata(req: IndexRequest, request: Request) -> IndexResponse:
    orchestrator = _get_ingest_orchestrator(request)
    result = orchestrator.ingest_domain("metadata", IngestionMode.FULL)
    return IndexResponse(
        domain="metadata",
        entities_indexed=result.entities_ingested,
        chunks_indexed=result.chunks_indexed,
        duration_ms=result.duration_ms,
    )


# ── Document Upload ────────────────────────────────────────────────────────────

@index_router.post("/domains/documents/files/upload", response_model=FileUploadResponse)
async def upload_document(file: UploadFile, request: Request) -> FileUploadResponse:
    t0 = time.monotonic()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 20MB limit")

    mime = file.content_type or ""
    if mime not in SUPPORTED_MIMES:
        raise HTTPException(status_code=415,
                            detail=f"Unsupported media type '{mime}'. "
                                   f"Supported: {sorted(SUPPORTED_MIMES)}")

    state = request.app.state
    fs_connector = state.registry.get("documents").connector

    entities = list(fs_connector.process_upload(content, file.filename or "upload", mime))

    # Separate doc entity (first) from sections
    doc_entity = next((e for e in entities if e.entity_type == "Document"), None)
    if not doc_entity:
        raise HTTPException(status_code=422, detail="Could not extract document entity")

    doc_id = doc_entity.entity_id
    title = doc_entity.name

    # Generate chunks and fan-out
    ingest_orch = _get_ingest_orchestrator(request)
    breadcrumb_gen = state.breadcrumb_gen
    doc_config = state.registry.get("documents")

    parent_of: dict[str, str | None] = {e.entity_id: e.parent_id for e in entities}
    chunks = [breadcrumb_gen.generate(e, doc_config, parent_chain=parent_of) for e in entities]
    ingest_orch._fan_out(chunks)

    # Index graph entities + relationships
    graph_nodes = 0
    try:
        graph_nodes = state.graph_writer.index_entities(entities, doc_config.graph_schema)
        state.graph_writer.index_relationships(entities, doc_config.graph_schema)
    except Exception:
        pass

    sections_indexed = len([e for e in entities if e.entity_type == "Section"])
    state.indexed_docs[doc_id] = title
    return FileUploadResponse(
        doc_id=doc_id, title=title,
        sections_indexed=sections_indexed,
        vector_docs=len(chunks), lucene_docs=len(chunks),
        graph_nodes=graph_nodes,
        duration_ms=(time.monotonic() - t0) * 1000,
        file_size_bytes=len(content),
    )


@index_router.get("/domains/documents/files", response_model=list[DocumentInfo])
async def list_documents(request: Request) -> list[DocumentInfo]:
    state = request.app.state
    docs = getattr(state, "indexed_docs", {})
    return [DocumentInfo(doc_id=k, title=v) for k, v in docs.items()]


@index_router.delete("/domains/documents/files/{doc_id}", status_code=204)
async def delete_document(doc_id: str, request: Request) -> None:
    state = request.app.state
    docs = getattr(state, "indexed_docs", {})
    if doc_id not in docs:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
    del docs[doc_id]
    try:
        state.vector_writer.clear_domain(f"doc_{doc_id}")
    except Exception:
        pass


# ── Debug ──────────────────────────────────────────────────────────────────────

@index_router.post("/debug/cypher")
async def debug_cypher(body: dict, request: Request) -> list[dict]:
    cypher = body.get("cypher", "")
    params = body.get("params", {})
    if not cypher:
        raise HTTPException(status_code=422, detail="'cypher' field required")
    return request.app.state.graph_writer.cypher_query(cypher, params)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_orchestrator(request: Request):
    orch = getattr(request.app.state, "search_orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="Search orchestrator not initialised")
    return orch


def _get_ingest_orchestrator(request: Request):
    orch = getattr(request.app.state, "ingest_orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="Ingestion orchestrator not initialised")
    return orch
