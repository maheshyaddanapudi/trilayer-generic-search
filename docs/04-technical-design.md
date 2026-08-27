# 04 — Technical Design

---

## 1. Project Structure

```
trilayer-generic-search/
├── docs/                           ← design docs (this directory)
├── src/
│   ├── __init__.py
│   ├── main.py                     ← FastAPI app + lifecycle
│   ├── config.py                   ← Settings (pydantic-settings)
│   │
│   ├── domain/                     ← Plugin layer
│   │   ├── __init__.py
│   │   ├── registry.py             ← DomainRegistry singleton
│   │   ├── config.py               ← DomainConfig + all config dataclasses
│   │   ├── connector.py            ← SourceConnector ABC
│   │   ├── entity_types.py         ← EntityTypeRegistry + EntityTypeDefinition
│   │   ├── graph_schema.py         ← GraphSchema + RelationshipDefinition etc
│   │   ├── breadcrumb.py           ← BreadcrumbTemplate ABC + TemplateBreadcrumbTemplate
│   │   └── intent_prompt.py        ← IntentPromptConfig
│   │
│   ├── connectors/                 ← SourceConnector implementations
│   │   ├── __init__.py
│   │   ├── xml_file.py             ← XMLFileConnector
│   │   ├── database.py             ← DatabaseConnector (SQLAlchemy)
│   │   ├── rest_api.py             ← RESTAPIConnector (httpx)
│   │   ├── file_system.py          ← FileSystemConnector (PDF, DOCX, XLSX)
│   │   ├── screen_context.py       ← ScreenContextConnector (request-time)
│   │   └── event_stream.py         ← EventStreamConnector (Kafka / webhook)
│   │
│   ├── indexers/                   ← IndexWriter implementations
│   │   ├── __init__.py
│   │   ├── base.py                 ← IndexWriter ABC
│   │   ├── vector.py               ← VectorIndexWriter (FAISS)
│   │   ├── lucene.py               ← LuceneIndexWriter (Whoosh)
│   │   └── graph.py                ← GraphIndexWriter (Neo4j)
│   │
│   ├── ingestion/                  ← Write path
│   │   ├── __init__.py
│   │   ├── orchestrator.py         ← IngestionOrchestrator
│   │   ├── breadcrumb_gen.py       ← BreadcrumbGenerator
│   │   └── change_detector.py      ← ChangeDetector + NeighbourPropagator
│   │
│   ├── session/                    ← Session Layer
│   │   ├── __init__.py
│   │   ├── registry.py             ← SessionRegistry (in-memory + TTL)
│   │   ├── search.py               ← SessionSearch (cosine scan)
│   │   └── materialiser.py         ← screen_context → SessionChunk conversion
│   │
│   ├── search/                     ← Read path
│   │   ├── __init__.py
│   │   ├── vector_search.py        ← VectorSearch (IndexReader)
│   │   ├── lucene_search.py        ← LuceneSearch (IndexReader)
│   │   ├── graph_search.py         ← GraphSearch (IndexReader)
│   │   └── orchestrator.py         ← SearchOrchestrator (LangGraph)
│   │
│   ├── aggregation/
│   │   ├── __init__.py
│   │   ├── base.py                 ← ResultPostProcessor ABC + AggregationPipeline
│   │   ├── rrf.py                  ← RRFAggregator
│   │   ├── graph_boost.py          ← GraphBoostingAggregator
│   │   └── session_link_boost.py   ← SessionLinkBoostingAggregator
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py               ← LLMClient ABC + AnthropicLLMClient
│   │   ├── intent_parser.py        ← IntentParser
│   │   └── synthesizer.py          ← Synthesizer
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── core.py                 ← All canonical dataclasses (RawEntity, MetadataChunk, etc)
│   │
│   └── api/
│       ├── __init__.py
│       └── routes.py               ← All FastAPI route handlers
│
├── plugins/                        ← Domain plugin implementations
│   ├── __init__.py
│   ├── financial_metadata/
│   │   ├── __init__.py
│   │   ├── plugin.py               ← builds DomainConfig for financial metadata
│   │   └── connector.py            ← XMLFileConnector subclass
│   ├── hr/
│   │   └── plugin.py
│   ├── compliance/
│   │   └── plugin.py
│   └── documents/
│       └── plugin.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── data/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## 2. Technology Choices

### 2.1 Vector Index

| Option | When to use | Trade-off |
|---|---|---|
| **FAISS CPU** (default) | Development, small corpora (<1M chunks) | In-memory; fast; no infra overhead; not persistent by default |
| **FAISS + disk persistence** | Medium corpora; single-node | `save_local` / `load_local`; still single-process |
| **PGVector** (POC 3 target) | Production; multi-process; filtered search | Needs PostgreSQL; supports metadata filtering natively |

**Embedding model:** `all-MiniLM-L6-v2` (384-dim, 80MB, CPU-fast).
Domain-specific fine-tuning is an extension point: swap via `EMBEDDING_MODEL` env var.

### 2.2 Keyword Index

| Option | When to use |
|---|---|
| **Whoosh** (default) | Development, single-node, simple queries |
| **Elasticsearch** | Production; distributed; richer query DSL; existing infra |

Both implement the same `LuceneIndexWriter` interface. Swap by changing the injected
implementation in `main.py`.

### 2.3 Graph Database

**Neo4j 5.x** — not swappable by design. The graph layer's value is Cypher's expressive
multi-hop traversal, which is native to Neo4j. The `GraphIndexWriter` interface exists to
abstract connection management and testing (mock driver in tests).

Key Neo4j patterns used:
- `MERGE` for idempotent upserts (safe to re-run indexing)
- Full-text index on `name` and `breadcrumb` properties
- Domain namespace prefix on all node labels (`{domain}_{EntityType}`)
- Relationship properties for `created_at` and `weight`

### 2.4 LLM Usage

Two LLM calls per search request:

| Call | Model | Input tokens | Purpose |
|---|---|---|---|
| Intent parsing | Claude Haiku (fast, cheap) | ~500 | Classify query, extract entities, expand terms |
| Synthesis | Claude Sonnet (capable) | ~3000 (breadcrumbs) | Generate grounded natural language answer |

Using different models for the two calls optimises cost + latency. Both are injectable.

**Prompt caching:** Intent parsing system prompt is static per domain — ideal for
Anthropic's prompt caching (cache the system prompt, pay only for user query tokens).

### 2.5 Orchestration

**LangGraph** `StateGraph` with these nodes:

```python
graph = StateGraph(SearchState)
graph.add_node("parse_intent",  parse_intent_node)
graph.add_node("tri_search",    tri_search_node)    # async parallel
graph.add_node("aggregate",     aggregate_node)
graph.add_node("synthesize",    synthesize_node)

graph.set_entry_point("parse_intent")
graph.add_edge("parse_intent", "tri_search")
graph.add_edge("tri_search",   "aggregate")
graph.add_edge("aggregate",    "synthesize")
graph.set_finish_point("synthesize")
```

Conditional edges are used if a domain has disabled certain indices
(e.g., a domain with no graph structure skips the graph search node).

---

## 3. Session Layer Implementation

### 3.0 Memory Model

The Session Layer is entirely in-process Python memory. No Redis, no database.

```
SessionRegistry._sessions: dict[session_id, list[SessionChunk]]
SessionRegistry._lock: asyncio.Lock   ← protects concurrent writes

Max chunks per session:  200 (configurable SESSION_MAX_CHUNKS)
Default TTL:             1800 seconds / 30 minutes (SESSION_TTL_SECONDS)
Purge schedule:          every 5 minutes via FastAPI background task
Max total sessions:      10,000 (configurable SESSION_MAX_TOTAL)
```

### Session Chunk Embedding

SessionChunks are embedded lazily at search time, not at write time:

```python
# SessionSearch.search() pseudocode
chunks = await registry.get_chunks(session_id)
if not chunks:
    return []

# Embed all session chunks in one batch (N is small, typically < 20)
texts = [c.breadcrumb for c in chunks]
chunk_vectors = embedder.encode(texts)          # same model as VectorSearch

# Embed query
query_text = " ".join(intent.entities + intent.expanded_terms)
query_vector = embedder.encode(query_text)

# Cosine similarity (no FAISS needed — linear scan is fine at this N)
scores = cosine_similarity([query_vector], chunk_vectors)[0]
ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
return [SearchResult(chunk=c.to_metadata_chunk(), score=s, rank=i+1,
                     sources=["session"]) for i, (c, s) in enumerate(ranked[:top_k])]
```

### Screen Context Materialisation

```python
# SessionRegistry.materialise_screen_context() pseudocode
session_chunks = []
for entity_id in screen_context.get("visible_accounts", []):
    # Look up the permanent chunk_id for this entity
    perm_chunk_id = f"{domain}::Account::{entity_id}"
    # Look up its breadcrumb from the permanent index
    perm_chunk = vector_writer.get_chunk(perm_chunk_id)

    session_chunk = SessionChunk(
        chunk_id=f"session::{session_id}::screen::{entity_id}",
        session_id=session_id,
        source_type=SessionSourceType.SCREEN_CONTEXT,
        domain=domain,
        name=perm_chunk.name if perm_chunk else entity_id,
        description=f"Currently visible on screen: {entity_id}",
        breadcrumb=perm_chunk.breadcrumb if perm_chunk else entity_id,
        attributes=screen_context,
        linked_permanent_ids=[perm_chunk_id] if perm_chunk else [],
        ttl_seconds=SESSION_TTL_SECONDS,
    )
    await registry.add_chunk(session_id, session_chunk)
    session_chunks.append(session_chunk)
return session_chunks
```

### Session Link Boosting

```python
# SessionLinkBoostingAggregator.process() pseudocode
session_results = results.get("session", [])
if not session_results:
    return current_merged_list

# Collect all permanent chunk_ids linked from session chunks
linked_ids = set()
for sr in session_results:
    chunk = sr.chunk
    # linked_permanent_ids stored in attributes by session materialiser
    linked_ids.update(chunk.attributes.get("_linked_permanent_ids", []))

boost_factor = config.session_link_boost_factor  # default 1.3

# Boost any permanent result whose chunk_id is in linked_ids
for result in current_merged_list:
    if result.chunk.chunk_id in linked_ids:
        result.rrf_score *= boost_factor
        result.boost_applied = True

# Re-sort
return sorted(current_merged_list, key=lambda r: r.rrf_score, reverse=True)[:top_k]
```

---

## 4. Ingestion Implementation Details

### 3.1 Batch Size and Memory

```
Default batch size: 100 entities per write call
Embedding batch:    32 sentences per encode() call (sentence-transformers default)
Neo4j batch:        UNWIND for bulk MERGE (100 nodes per transaction)
```

### 3.2 Breadcrumb Generation

```python
# Pseudocode for BreadcrumbGenerator.generate()
def generate(entity: RawEntity, domain_id: str) -> MetadataChunk:
    config = registry.get(domain_id)
    template = config.breadcrumb_template

    # Build ancestor chain for lineage slot
    ancestors = graph_writer.get_ancestors(entity.entity_id, domain_id)
    context = BreadcrumbContext(ancestors=ancestors, domain_name=domain_id)

    breadcrumb = template.generate(entity, context)

    return MetadataChunk(
        chunk_id=f"{domain_id}::{entity.entity_type}::{entity.entity_id}",
        domain=domain_id,
        element_id=entity.entity_id,
        element_type=entity.entity_type,
        name=entity.name,
        description=entity.description,
        breadcrumb=breadcrumb,
        lineage_path=[a.name for a in ancestors] + [entity.name],
        attributes=entity.properties,
        source_url=entity.source_url,
    )
```

### 3.3 On-Upload Indexing

When a file is uploaded via `POST /domains/{id}/files/upload`:

```
File received (binary)
        │
        ▼
FileSystemConnector.process_upload(file_bytes, filename, mime_type)
        │
        ├── Text extraction (pdfminer, python-docx, openpyxl)
        ├── Section detection (heading heuristics)
        └── Yields RawEntity per section / chunk
        │
        ▼
IngestionOrchestrator.ingest_entities(entities, domain_id)
        │
        ├── BreadcrumbGenerator → MetadataChunk per section
        └── Fan-out to VectorIndexWriter, LuceneIndexWriter, GraphIndexWriter
        │
        ▼
File immediately searchable (target: < 10s for a 50-page PDF)
```

The upload endpoint returns an `IngestionResult` synchronously so the caller
knows exactly what was indexed. For large files (>50 pages), the endpoint
accepts a `background=true` flag and returns a job ID for polling.

---

## 4. Search Implementation Details

### 4.1 Vector Search Query Construction

```python
# Combine entities + expanded terms into one embedding query
query_text = " ".join(intent.entities + intent.expanded_terms)
if intent.domain_context:
    # Prepend visible context for screen-grounded queries
    ctx = " ".join(str(v) for v in intent.domain_context.values())
    query_text = f"{ctx} {query_text}"

query_vector = embedder.encode(query_text)
results = vector_writer.similarity_search(
    query_vector, top_k=top_k, domain=intent.target_domain
)
```

### 4.2 Lucene Search Query Construction

```python
# Entity-first: exact match on name field
# Fallback: BM25 across breadcrumb field
if intent.query_type == QueryType.LOOKUP:
    query = Or([Term("name", e) for e in intent.entities])
else:
    terms = intent.entities + intent.expanded_terms
    query = MultifieldParser(["name", "breadcrumb"], schema).parse(" ".join(terms))
```

### 4.3 Graph Search Query Construction

```python
if intent.cypher_hint:
    # Use LLM-generated Cypher directly
    rows = graph_writer.cypher_query(intent.cypher_hint, params={})
else:
    # Entity lookup: find nodes matching extracted entity names
    cypher = """
    MATCH (n)
    WHERE n.code IN $codes OR n.name IN $names
    RETURN n LIMIT $limit
    """
    rows = graph_writer.cypher_query(cypher, {
        "codes": intent.entities,
        "names": intent.entities,
        "limit": top_k,
    })
```

### 4.4 RRF Implementation

```python
def rrf_merge(
    results_by_source: dict[str, list[SearchResult]],
    k: int = 60,
    top_k: int = 10,
) -> list[SearchResult]:
    scores: dict[str, float] = defaultdict(float)
    by_chunk_id: dict[str, SearchResult] = {}
    source_sets: dict[str, set[str]] = defaultdict(set)

    for source, results in results_by_source.items():
        for rank, result in enumerate(results, start=1):
            cid = result.chunk.chunk_id
            scores[cid] += 1.0 / (k + rank)
            by_chunk_id[cid] = result
            source_sets[cid].add(source)

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]

    merged = []
    for i, cid in enumerate(sorted_ids, start=1):
        r = by_chunk_id[cid]
        r.rrf_score = scores[cid]
        r.rank = i
        r.sources = list(source_sets[cid])
        merged.append(r)

    return merged
```

---

## 5. Performance Targets

| Operation | Target | Notes |
|---|---|---|
| Full search (e2e) | < 2s | Including both LLM calls |
| Intent parsing only | < 300ms | Claude Haiku; cached system prompt |
| Tri-dispatch (parallel) | < 500ms | Vector + Lucene dominate; graph ~200ms |
| Aggregation | < 10ms | Pure Python; no I/O |
| Synthesis | < 1s | Claude Sonnet; ~3K input tokens |
| File upload + index | < 10s | For a 50-page PDF |
| Session chunk write | < 1ms | In-memory dict insert |
| Session search (cosine scan) | < 5ms | Linear over ≤ 200 chunks; same embedder |
| Screen context materialise | < 50ms | Includes graph lookup for chunk_ids |
| Incremental CDC update | < 5s | Single entity + neighbour propagation |
| Full re-index (10K entities) | < 60s | Batch writes to all three indices |

---

## 6. Scalability Considerations

| Concern | Approach |
|---|---|
| Large corpora (>1M chunks) | Migrate FAISS → PGVector; Whoosh → Elasticsearch |
| Multiple simultaneous searches | FastAPI async handles concurrent requests; asyncio.gather for tri-dispatch |
| Multiple domains | Each domain has isolated index partitions; no contention |
| Heavy ingestion load | Background task queue (Celery or asyncio task group) for large batch jobs |
| Graph traversal depth | Neo4j handles multi-hop natively; `max_depth` cap per domain prevents runaway queries |

---

## 7. Security Considerations

| Concern | Mitigation |
|---|---|
| LLM prompt injection via query | Intent parser uses strict JSON output schema; non-JSON output is rejected |
| Cypher injection | LLM-generated Cypher is validated against domain's allowed relationship types before execution |
| Cross-domain data leakage | Domain namespace isolation; search requests scoped by domain_id |
| API key exposure | All secrets via environment variables; never in code or config files |
| Debug endpoints in production | `/debug/cypher` and `/debug/vector` protected by auth middleware |
| File upload path traversal | File uploads validated for MIME type; stored in isolated domain directory |

---

## 8. Testing Strategy

```
tests/
├── unit/
│   ├── test_rrf_aggregator.py          ← Pure math; no I/O
│   ├── test_breadcrumb_generator.py    ← Template rendering
│   ├── test_intent_parser.py           ← LLM mock; heuristic fallback
│   ├── test_graph_schema.py            ← Schema validation
│   └── test_domain_config.py           ← Config validation
│
├── integration/
│   ├── test_vector_indexer.py          ← Requires FAISS
│   ├── test_lucene_indexer.py          ← Requires Whoosh on disk
│   ├── test_graph_indexer.py           ← Requires Neo4j (Docker)
│   ├── test_ingestion_orchestrator.py  ← Full write path
│   ├── test_search_orchestrator.py     ← Full read path (LLM mocked)
│   └── test_api.py                     ← FastAPI TestClient
│
└── conftest.py                         ← Shared fixtures, mock LLM client
```

LLM calls are **always mocked** in tests. A `MockLLMClient` returns deterministic
JSON for known prompts, enabling fast, reproducible CI runs.

---

## 9. Dependencies (requirements.txt additions)

```
# API
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
pydantic-settings>=2.2.0

# LLM + Orchestration
anthropic>=0.28.0
langgraph>=0.1.0
langchain-anthropic>=0.1.0

# Vector
faiss-cpu>=1.8.0
sentence-transformers>=3.0.0

# Keyword
Whoosh>=2.7.4

# Graph
neo4j>=5.20.0

# File parsing (document plugin)
pdfminer.six>=20221105
python-docx>=1.1.0
openpyxl>=3.1.0

# HTTP (REST API connector)
httpx>=0.27.0

# Utilities
lxml>=5.2.0
python-dateutil>=2.9.0
```
