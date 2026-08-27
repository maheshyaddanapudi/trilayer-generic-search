# MVP 01 — System Architecture

---

## 1. MVP System Context

```mermaid
graph TB
    subgraph Users
        BU[Business User\nnatural language queries]
        DE[Data Engineer\nexact technical IDs]
        BD[BI Developer\nhierarchy / lineage]
        ADM[Admin\nupload files, trigger index]
    end

    subgraph Sources
        XML[Financial planning\nXML metadata export]
        FILES[PDF / DOCX / XLSX\nPolicy docs, SOPs, guides]
    end

    MVP[Trilayer Generic Search\nPhase 1 MVP]
    LLM[Anthropic Claude API]

    BU -->|natural language query| MVP
    DE -->|exact code lookup| MVP
    BD -->|hierarchy query| MVP
    ADM -->|POST /index or file upload| MVP

    XML -->|startup auto-index| MVP
    FILES -->|POST /upload → immediate index| MVP

    MVP -->|intent parse + synthesize| LLM
    MVP -->|grounded answer + citations| BU
```

---

## 2. MVP Container Diagram

```mermaid
graph TB
    subgraph MVP [Phase 1 MVP — Single Docker Compose Stack]
        API[FastAPI app\nport 8000]

        subgraph WritePath [Write Path]
            XML_CON[XMLFileConnector\nfinancial planning XML]
            FS_CON[FileSystemConnector\nPDF / DOCX / XLSX]
            BG[BreadcrumbGenerator]
            IO[IngestionOrchestrator]
        end

        subgraph IndexLayer [Tri-Index — drivers in tgs-app process]
            VI[VectorIndexWriter\nPGVector driver]
            LI[LuceneIndexWriter\nWhoosh\non-disk]
            GI[GraphIndexWriter\nNeo4j driver]
        end

        subgraph QueryPath [Read Path]
            IP[IntentParser\nClaude Haiku]
            QD[TripleDispatch\nasyncio.gather]
            AGG[AggregationPipeline\nRRF + GraphBoost]
            SYN[Synthesizer\nClaude Sonnet]
        end

        subgraph Plugins [Domain Plugins — registered at startup]
            FMP[MetadataPlugin\ndomain_id: metadata]
            DP[DocumentPlugin\ndomain_id: documents]
        end
    end

    subgraph Storage
        NEO4J[(Neo4j 5.x\nBolt :7687\nVolume: neo4j_data)]
        WHOOSH[(Whoosh index\non-disk\nVolume: whoosh_data)]
        PGVEC[(PostgreSQL + pgvector\nHNSW index :5432\nVolume: pgvector_data)]
    end

    LLM_EXT[Anthropic API]
    FILE_STORE[data/uploads\nfile storage]

    API --> IO
    API --> IP
    IO --> VI & LI & GI
    QD --> VI & LI & GI
    GI --> NEO4J
    LI --> WHOOSH
    VI --> PGVEC
    FS_CON --> FILE_STORE
    IP --> LLM_EXT
    SYN --> LLM_EXT
    FMP --> IO
    DP --> IO
    FMP --> IP
    DP --> IP
```

---

## 3. Architectural Layers — MVP Scope

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 0 — API Surface                                           │
│  FastAPI · /search · /index · /upload · /health                 │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 1 — Domain Plugins                            2 PLUGINS   │
│                                                                  │
│  MetadataPlugin          DocumentPlugin                 │
│  ─────────────────────────        ──────────────                 │
│  XMLFileConnector                 FileSystemConnector            │
│  6 entity types                   2 entity types                 │
│  7 relationship types             3 relationship types           │
│  MetadataBreadcrumbTemplate      DocumentBreadcrumbTemplate     │
│  MetadataIntentPromptConfig       DocumentIntentPromptConfig     │
│  Trigger: startup + manual        Trigger: on-upload + manual    │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Ingestion Pipeline                         FIXED      │
│  IngestionOrchestrator · BreadcrumbGenerator                     │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 3 — Tri-Index Store                            FIXED      │
│  PGVector (vector) · Whoosh (lucene) · Neo4j (graph)            │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 4 — Query Pipeline                             FIXED      │
│  IntentParser · TripleDispatch · VectorSearch                    │
│  LuceneSearch · GraphSearch                                      │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 5 — Aggregation Pipeline                       FIXED      │
│  RRFAggregator · GraphBoostingAggregator                         │
├──────────────────────────────────────────────────────────────────┤
│  LAYER 6 — LLM Services                               FIXED      │
│  AnthropicLLMClient · IntentParser · Synthesizer                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. MVP Deployment

Single `docker-compose.yml` with three services:

```
┌──────────────────────────────────────────────────────────────────┐
│  Docker Compose — tgs_mvp_network                                │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │  tgs-app         │  │  neo4j           │  │  postgres     │  │
│  │  FastAPI :8000   │  │  Bolt    :7687   │  │  :5432        │  │
│  │  Whoosh (on-disk)│  │  Browser :7474   │  │  pgvector ext │  │
│  └──────────────────┘  └──────────────────┘  │  HNSW index   │  │
│                                               └───────────────┘  │
│  Volumes:                                                        │
│    neo4j_data   — persistent graph                               │
│    whoosh_data  — persistent keyword index                       │
│    pgvector_data— persistent vector index                        │
│    uploads      — uploaded files                                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. MVP Architectural Decisions

### ADR-MVP-01: Optional domain filter; null = full scope
**Decision:** The search request accepts an optional `domain` field. When specified (`metadata`
or `documents`), the search is scoped to that domain only. When `null`, all registered domains are
searched and results are merged via RRF across all three indices for each domain.
**Rationale:** Domain filter enables precise targeted queries for users who know which corpus to search.
Null full-scope keeps the API simple for exploratory queries. No cross-domain vocabulary scoring is
needed since RRF handles merging by rank position alone.

### ADR-MVP-02: PGVector for vector storage
**Decision:** Vectors are stored in PostgreSQL via the `pgvector` extension, using an HNSW
index for approximate nearest-neighbour search.
**Rationale:** Persistent from day one — no re-embedding on restart. Metadata filtering
(by `domain_id` column) co-located with the vectors. HNSW latency is negligible vs FAISS
at the expected MVP corpus size (< 50K chunks). PostgreSQL is a standard dependency that
most teams already operate.
**Config:** `POSTGRES_URL=postgresql://tgs:tgs_password@postgres:5432/tgs_db`

### ADR-MVP-03: File upload is synchronous for files ≤ 20MB
**Decision:** `POST /upload` processes and indexes the file before returning HTTP 200.
Background jobs are not implemented in Phase 1.
**Rationale:** 20MB covers typical policy documents (50–100 pages PDF). Files over this
limit return 413 with guidance to contact the admin for bulk ingestion.

### ADR-MVP-04: Two separate graph namespaces
**Decision:** Metadata domain nodes use label prefix `meta_` (e.g., `meta_Account`).
Document nodes use label prefix `doc_` (e.g., `doc_Document`, `doc_Section`).
**Rationale:** Prevents accidental Cypher queries from crossing domains.
**Impact:** Cypher hints generated by the intent parser must use the correct prefix.
