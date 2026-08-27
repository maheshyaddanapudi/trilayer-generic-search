# MVP 04 — Technical Design

---

## 1. MVP Project Structure

```
trilayer-generic-search/
├── docs/
│   ├── *.md                        ← generic framework docs
│   └── mvp/                        ← this directory
│
├── src/
│   ├── __init__.py
│   ├── main.py                     ← FastAPI app + startup lifecycle
│   ├── config.py                   ← Settings via pydantic-settings
│   │
│   ├── models/
│   │   └── core.py                 ← RawEntity, MetadataChunk, SearchResult,
│   │                                  ParsedIntent, SearchState
│   │
│   ├── domain/                     ← Generic plugin interfaces
│   │   ├── registry.py             ← DomainRegistry singleton
│   │   ├── config.py               ← DomainConfig + TriggerConfig dataclasses
│   │   ├── connector.py            ← SourceConnector ABC
│   │   ├── entity_types.py         ← EntityTypeRegistry + EntityTypeDefinition
│   │   ├── graph_schema.py         ← GraphSchema + RelationshipDefinition
│   │   ├── breadcrumb.py           ← BreadcrumbTemplate + TemplateBreadcrumbTemplate
│   │   └── intent_prompt.py        ← IntentPromptConfig
│   │
│   ├── connectors/
│   │   ├── xml_file.py             ← XMLFileConnector (metadata XML)
│   │   └── file_system.py          ← FileSystemConnector (PDF/DOCX/XLSX)
│   │
│   ├── indexers/
│   │   ├── base.py                 ← IndexWriter ABC
│   │   ├── vector.py               ← VectorIndexWriter (PGVector)
│   │   ├── lucene.py               ← LuceneIndexWriter (Whoosh)
│   │   └── graph.py                ← GraphIndexWriter (Neo4j)
│   │
│   ├── ingestion/
│   │   ├── orchestrator.py         ← IngestionOrchestrator
│   │   ├── breadcrumb_gen.py       ← BreadcrumbGenerator
│   │   └── change_detector.py      ← ChangeDetector (basic, no CDC in MVP)
│   │
│   ├── search/
│   │   ├── vector_search.py        ← VectorSearch
│   │   ├── lucene_search.py        ← LuceneSearch
│   │   ├── graph_search.py         ← GraphSearch
│   │   └── orchestrator.py         ← SearchOrchestrator (LangGraph)
│   │
│   ├── aggregation/
│   │   ├── base.py                 ← ResultPostProcessor + AggregationPipeline
│   │   ├── rrf.py                  ← RRFAggregator
│   │   └── graph_boost.py          ← GraphBoostingAggregator
│   │
│   ├── llm/
│   │   ├── client.py               ← LLMClient ABC + AnthropicLLMClient
│   │   ├── intent_parser.py        ← IntentParser
│   │   └── synthesizer.py          ← Synthesizer
│   │
│   └── api/
│       └── routes.py               ← All FastAPI route handlers
│
├── plugins/
│   ├── metadata/
│   │   ├── __init__.py
│   │   ├── plugin.py               ← Builds METADATA_DOMAIN DomainConfig
│   │   └── connector.py            ← XMLFileConnector subclass (if needed)
│   └── documents/
│       ├── __init__.py
│       └── plugin.py               ← Builds DOCUMENT_DOMAIN DomainConfig
│
├── tests/
│   ├── unit/
│   │   ├── test_rrf.py
│   │   ├── test_breadcrumb_metadata.py
│   │   ├── test_breadcrumb_document.py
│   │   └── test_intent_parser.py
│   ├── integration/
│   │   ├── test_metadata_search.py
│   │   └── test_document_upload_search.py
│   └── conftest.py
│
├── data/
│   ├── sample_metadata.xml         ← metadata seed data
│   └── uploads/                    ← file upload directory (gitignored)
│
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## 2. Technology Stack — MVP

| Concern | MVP Choice | Notes |
|---|---|---|
| API | FastAPI 0.111+ | Async, auto-OpenAPI |
| Vector index | PGVector | PostgreSQL extension; persistent via Docker volume |
| Keyword index | Whoosh | On-disk via Docker volume |
| Graph DB | Neo4j 5.x | Persistent via Docker volume |
| Embeddings | `all-MiniLM-L6-v2` | 384-dim; ~80MB; CPU-only |
| LLM — Intent | Claude Haiku | Fast, cheap; cached system prompt |
| LLM — Synthesis | Claude Sonnet | High quality grounded answers |
| Orchestration | LangGraph | 4-node state machine |
| PDF extraction | `pdfminer.six` | Text + structure from PDF |
| DOCX extraction | `python-docx` | Heading-aware section detection |
| XLSX extraction | `openpyxl` | Sheet rows → section entities |
| XML parsing | `lxml` | Existing POC pattern |
| HTTP | `httpx` | Async HTTP (future connectors) |
| Language | Python 3.11+ | Consistent with existing POC |
| Container | Docker Compose | tgs-app + neo4j + postgres |

---

## 3. Startup Sequence

```python
# src/main.py — startup_event()

@app.on_event("startup")
async def startup_event():
    # 1. Connect to Neo4j
    graph_writer = GraphIndexWriter(uri, user, password)

    # 2. Connect to PGVector + load embedding model
    vector_writer = VectorIndexWriter(
        postgres_url=settings.postgres_url,
        model_name=settings.embedding_model,
    )  # creates metadata_chunks table + HNSW index if not exists
    lucene_writer = LuceneIndexWriter(index_dir=Path(settings.whoosh_dir))

    # 3. Register domain plugins
    registry = DomainRegistry.get_instance()
    registry.register(METADATA_DOMAIN)
    registry.register(DOCUMENT_DOMAIN)

    # 4. Auto-index metadata on startup
    orchestrator = IngestionOrchestrator(registry, vector_writer, lucene_writer, graph_writer, breadcrumb_gen)
    await orchestrator.ingest_domain("metadata", IngestionMode.FULL)
    # Documents domain: no startup ingest (uploads dir starts empty)

    # 5. Wire LLM + search
    llm_client     = AnthropicLLMClient(api_key=settings.anthropic_api_key)
    intent_parser  = IntentParser(llm_client, registry)
    synthesizer    = Synthesizer(llm_client)

    aggregation_pipeline = AggregationPipeline([
        RRFAggregator(),
        GraphBoostingAggregator(graph_writer),
    ])

    search_orchestrator = SearchOrchestrator(
        vector_search=VectorSearch(vector_writer, vector_writer._model),
        lucene_search=LuceneSearch(lucene_writer),
        graph_search=GraphSearch(graph_writer),
        intent_parser=intent_parser,
        synthesizer=synthesizer,
        aggregation_pipeline=aggregation_pipeline,
        domain_registry=registry,
    )
    app.state.search_orchestrator = search_orchestrator
    # ... store all on app.state
```

---

## 4. VectorIndexWriter — PGVector Schema

```sql
-- Created on first startup; idempotent
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS metadata_chunks (
    chunk_id    TEXT        PRIMARY KEY,
    domain_id   TEXT        NOT NULL,
    entity_id   TEXT,
    entity_type TEXT,
    breadcrumb  TEXT        NOT NULL,
    embedding   vector(384),
    properties  JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- HNSW index for fast approximate cosine similarity
CREATE INDEX IF NOT EXISTS metadata_chunks_embedding_idx
    ON metadata_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Domain filter index (used in domain-scoped queries)
CREATE INDEX IF NOT EXISTS metadata_chunks_domain_idx
    ON metadata_chunks (domain_id);
```

Similarity search query (domain-scoped):
```sql
SELECT chunk_id, breadcrumb, entity_id, entity_type, domain_id,
       1 - (embedding <=> $1::vector) AS score
FROM metadata_chunks
WHERE domain_id = $2
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

Full-scope search (domain = null):
```sql
SELECT chunk_id, breadcrumb, entity_id, entity_type, domain_id,
       1 - (embedding <=> $1::vector) AS score
FROM metadata_chunks
ORDER BY embedding <=> $1::vector
LIMIT $2;
```

---

## 5. FileSystemConnector — Text Extraction


```python
class FileSystemConnector(SourceConnector):

    def process_upload(
        self, file_bytes: bytes, filename: str, mime_type: str
    ) -> Iterator[RawEntity]:
        doc_id   = str(uuid4())
        title    = Path(filename).stem
        sections = self._extract_sections(file_bytes, mime_type, title)
        doc_entity = self._make_document_entity(doc_id, title, mime_type, len(sections))
        yield doc_entity
        for section in sections:
            yield self._make_section_entity(section, doc_id, title)

    def _extract_sections(self, data: bytes, mime: str, title: str) -> list[RawSection]:
        if mime == "application/pdf":
            return self._extract_pdf(data)
        elif "wordprocessingml" in mime:
            return self._extract_docx(data)
        elif "spreadsheetml" in mime:
            return self._extract_xlsx(data)

    def _extract_pdf(self, data: bytes) -> list[RawSection]:
        # pdfminer.six LAParams extraction
        # Heuristic: lines in ALL CAPS or matching §N pattern → new section heading
        # Returns RawSection(heading, content_text, page_number, order_index)

    def _extract_docx(self, data: bytes) -> list[RawSection]:
        # python-docx: paragraphs with style.name in ('Heading 1', 'Heading 2', 'Heading 3')
        # → new section boundary

    def _extract_xlsx(self, data: bytes) -> list[RawSection]:
        # openpyxl: each worksheet → one section
        # heading = sheet.title, content = first 10 rows as text
```

---

## 6. LangGraph Pipeline — MVP

```python
# src/search/orchestrator.py

def _build_graph(self) -> StateGraph:
    graph = StateGraph(SearchState)

    graph.add_node("parse_intent",  self._parse_intent_node)
    graph.add_node("triple_search", self._triple_search_node)   # asyncio.gather × 3
    graph.add_node("aggregate",     self._aggregate_node)
    graph.add_node("synthesize",    self._synthesize_node)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent",  "triple_search")
    graph.add_edge("triple_search", "aggregate")
    graph.add_edge("aggregate",     "synthesize")
    graph.set_finish_point("synthesize")

    return graph.compile()

async def _triple_search_node(self, state: SearchState) -> SearchState:
    intent = state["intent"]
    top_k  = 10

    vector_task = asyncio.to_thread(self._vector.search, intent, top_k)
    lucene_task = asyncio.to_thread(self._lucene.search, intent, top_k)
    graph_task  = asyncio.to_thread(self._graph.search,  intent, top_k)

    v, l, g = await asyncio.gather(vector_task, lucene_task, graph_task)

    return {**state, "vector_results": v, "lucene_results": l, "graph_results": g}
```

---

## 7. MVP Performance Targets

| Operation | Target |
|---|---|
| Full metadata search (e2e) | < 2s |
| Intent parsing (Claude Haiku) | < 300ms |
| Triple-dispatch (parallel, PGVector + Whoosh + Neo4j) | < 600ms |
| Aggregation (all 3 stages) | < 15ms |
| Synthesis (Claude Sonnet) | < 1.2s |
| File upload + index (10-page PDF) | < 5s |
| File upload + index (50-page PDF) | < 15s |
| Startup (index XML + load model) | < 30s |

---

## 8. MVP Configuration (`.env`)

```
# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# LLM
ANTHROPIC_API_KEY=sk-ant-...
INTENT_MODEL=claude-haiku-4-5-20251001
SYNTHESIS_MODEL=claude-sonnet-4-6

# Embedding
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# PostgreSQL (vector store — pgvector)
POSTGRES_URL=postgresql://tgs:tgs_password@postgres:5432/tgs_db
POSTGRES_VECTOR_TABLE=metadata_chunks

# Keyword index storage
WHOOSH_INDEX_DIR=./data/whoosh

# Ingestion
METADATA_FILE=./data/sample_metadata.xml
UPLOADS_DIR=./data/uploads
MAX_UPLOAD_SIZE_MB=20
DEFAULT_BATCH_SIZE=100
MAX_BREADCRUMB_LENGTH=512

# Aggregation
RRF_K=60
GRAPH_BOOST_FACTOR=1.5
GRAPH_BOOST_TOP_N=3

# API
API_HOST=0.0.0.0
API_PORT=8000
```

---

## 9. MVP Requirements

```
# requirements.txt — MVP

# API
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
pydantic-settings>=2.2.0
python-multipart>=0.0.9       # file upload form data

# LLM + Orchestration
anthropic>=0.28.0
langgraph>=0.1.0

# Vector
pgvector>=0.3.0
psycopg2-binary>=2.9.9
sentence-transformers>=3.0.0

# Keyword
Whoosh>=2.7.4

# Graph
neo4j>=5.20.0

# XML (metadata)
lxml>=5.2.0

# File extraction (documents)
pdfminer.six>=20221105
python-docx>=1.1.0
openpyxl>=3.1.0

# Utilities
python-dateutil>=2.9.0

# Testing
pytest>=8.2.0
pytest-asyncio>=0.23.0
httpx>=0.27.0                 # FastAPI test client
```

---

## 10. docker-compose.yml

```yaml
version: "3.9"

services:
  tgs-app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=password
      - POSTGRES_URL=postgresql://tgs:tgs_password@postgres:5432/tgs_db
    env_file:
      - .env
    volumes:
      - whoosh_data:/app/data/whoosh
      - ./data:/app/data
    depends_on:
      neo4j:
        condition: service_healthy
      postgres:
        condition: service_healthy
    networks:
      - tgs_network

  neo4j:
    image: neo4j:5
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/password
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD", "wget", "-O-", "http://localhost:7474"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks:
      - tgs_network

  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=tgs
      - POSTGRES_PASSWORD=tgs_password
      - POSTGRES_DB=tgs_db
    volumes:
      - pgvector_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tgs -d tgs_db"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - tgs_network

volumes:
  neo4j_data:
  whoosh_data:
  pgvector_data:

networks:
  tgs_network:
```
