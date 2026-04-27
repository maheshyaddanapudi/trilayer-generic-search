# MVP 07 — Sequence Diagrams

---

## 1. App Startup — Metadata Auto-Index

```mermaid
sequenceDiagram
    participant App as main.py
    participant GI as GraphIndexWriter
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant Reg as DomainRegistry
    participant IO as IngestionOrchestrator
    participant XML as XMLFileConnector
    participant BG as BreadcrumbGenerator
    participant Neo4j

    App->>GI: GraphIndexWriter(uri, user, password)
    GI->>Neo4j: bolt://neo4j:7687 connect
    Neo4j-->>GI: connected
    App->>VI: VectorIndexWriter(model="all-MiniLM-L6-v2")
    Note over VI: loads model ~80MB, opens PGVector connection, creates HNSW schema
    App->>LI: LuceneIndexWriter(index_dir=./data/whoosh)
    Note over LI: creates metadata/ and documents/ subdirectories

    App->>Reg: DomainRegistry.get_instance()
    App->>Reg: register(METADATA_DOMAIN)
    App->>Reg: register(DOCUMENT_DOMAIN)

    App->>IO: IngestionOrchestrator(registry, vi, li, gi, bg)
    App->>IO: ingest_domain("metadata", IngestionMode.FULL)
    IO->>VI: clear domain partition "metadata"
    IO->>LI: wipe metadata index dir
    IO->>XML: fetch_all()

    loop for each RawEntity (~50 from sample_metadata.xml)
        XML-->>IO: RawEntity (Account / Version / Sheet / Level / Dimension / DimValue)
        IO->>BG: generate(entity, METADATA_DOMAIN)
        BG->>GI: get_ancestors(entity_id, domain) — for lineage in breadcrumb
        GI-->>BG: ancestor chain
        BG-->>IO: MetadataChunk(breadcrumb, embedding=None)
        par encode + fan-out
            IO->>VI: index([chunk]) — encode breadcrumb → 384-dim vector
            IO->>LI: index([chunk]) — tokenize into Whoosh schema
            IO->>GI: index([chunk]) — MERGE meta_* node
        end
    end

    IO->>GI: index_relationships(raw_entities, METADATA_GRAPH_SCHEMA)
    Note over GI: MERGE PARENT_OF, LINKED_TO, INCLUDES_ACCOUNT, etc.
    IO-->>App: IngestionResult(entities=50, chunks=50, graph_nodes=50, ms=...)
    Note over App: metadata domain ready; documents domain empty (no startup ingest)
```

---

## 2. File Upload → Immediate Indexing

```mermaid
sequenceDiagram
    participant Client
    participant Router as IndexRouter
    participant FS as FileSystemConnector
    participant TX as TextExtractor
    participant BG as BreadcrumbGenerator
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter

    Client->>Router: POST /domains/documents/files/upload (multipart/form-data)
    Router->>Router: check Content-Type — PDF / DOCX / XLSX only
    Router->>Router: check Content-Length ≤ 20MB
    Note over Router: return 413 if too large, 415 if wrong type

    Router->>FS: process_upload(file_bytes, filename, mime_type)
    FS->>FS: doc_id = uuid4()
    FS->>TX: extract_pdf / extract_docx / extract_xlsx(file_bytes)

    alt PDF
        TX->>TX: pdfminer.six LAParams extraction
        TX->>TX: heuristic: ALL CAPS lines or §N pattern → section boundary
    else DOCX
        TX->>TX: python-docx paragraph scan
        TX->>TX: Heading 1/2/3 style → section boundary
    else XLSX
        TX->>TX: openpyxl worksheet iteration
        TX->>TX: each sheet.title → one section
    end

    TX-->>FS: list[RawSection(heading, content_text, page_number, order_index)]
    FS-->>Router: yield RawEntity(Document, doc_id, title, mime, section_count)

    loop for each RawSection
        FS-->>Router: yield RawEntity(Section, section_id, heading, content_summary, page)
    end

    loop for each RawEntity
        Router->>BG: generate(entity, DOCUMENT_DOMAIN)
        BG-->>Router: MetadataChunk with breadcrumb
        par encode + fan-out
            Router->>VI: index([chunk])
            Router->>LI: index([chunk])
            Router->>GI: index([chunk]) — MERGE doc_Document, doc_Section, HAS_SECTION
        end
    end

    Router-->>Client: 200 FileUploadResponse(doc_id, title, sections_indexed, vector_docs, lucene_docs, graph_nodes, duration_ms)
    Note over Client: document is immediately searchable — all three indices updated
```

---

## 3. Search — Single Domain (Metadata)

```mermaid
sequenceDiagram
    participant Client
    participant SR as SearchRouter
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant Haiku as Claude Haiku
    participant VS as VectorSearch
    participant LS as LuceneSearch
    participant GS as GraphSearch
    participant RRF as RRFAggregator
    participant GB as GraphBoostingAggregator
    participant SYN as Synthesizer
    participant Sonnet as Claude Sonnet

    Client->>SR: POST /search {query: "recurring revenue accounts", domain: "metadata"}
    SR->>SO: run("recurring revenue accounts", domain="metadata")

    Note over SO: LangGraph Node 1 — parse_intent
    SO->>IP: parse(query, METADATA_DOMAIN.intent_prompt)
    IP->>Haiku: POST /messages — intent classification + synonym expansion
    Note over Haiku: fast, ~200ms, cached system prompt
    Haiku-->>IP: {type: DISCOVERY, expanded_query: "arr mrr saas subscription revenue", entity_hint: Account}
    IP-->>SO: ParsedIntent(DISCOVERY, confidence=0.92)

    Note over SO: LangGraph Node 2 — triple_search (asyncio.gather)
    par parallel dispatch
        SO->>VS: search(intent, top_k=10, domain="metadata")
        Note over VS: PGVector HNSW cosine similarity, filter by meta_ prefix
        VS-->>SO: vector_results[10]
    and
        SO->>LS: search(intent, top_k=10, domain="metadata")
        Note over LS: Whoosh BM25 in metadata/ dir
        LS-->>SO: lucene_results[10]
    and
        SO->>GS: search(intent, top_k=10, domain="metadata")
        Note over GS: Cypher on meta_Account nodes, embedding similarity via Neo4j
        GS-->>SO: graph_results[10]
    end

    Note over SO: LangGraph Node 3 — aggregate
    SO->>RRF: merge(vector[10], lucene[10], graph[10])
    RRF-->>SO: rrf_merged[10] — scores via Σ 1/(60+rank_i)
    SO->>GB: boost(rrf_merged, top_lucene=3)
    GB->>GS: get_neighbours(top_lucene_chunk_ids, ["PARENT_OF","LINKED_TO"], depth=1)
    GS-->>GB: neighbour_chunks
    GB-->>SO: final_results[10] with graph-boosted scores

    Note over SO: LangGraph Node 4 — synthesize
    SO->>SYN: synthesize(query, final_results[10], METADATA_DOMAIN)
    SYN->>Sonnet: POST /messages — grounded synthesis, breadcrumbs as context
    Note over Sonnet: "Answer ONLY using provided breadcrumbs"
    Sonnet-->>SYN: "Found 3 relevant accounts for 'recurring revenue':\n1. SAAS_REVENUE..."
    SYN-->>SO: synthesis text

    SO-->>SR: SearchState
    SR-->>Client: 200 SearchResponse(results[10], synthesis, intent, latency_ms=850)
```

---

## 4. Search — Full Scope (domain = null)

```mermaid
sequenceDiagram
    participant Client
    participant SR as SearchRouter
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant Haiku as Claude Haiku
    participant VS as VectorSearch
    participant LS as LuceneSearch
    participant GS as GraphSearch
    participant AGG as AggregationPipeline
    participant SYN as Synthesizer

    Client->>SR: POST /search {query: "approval policy for large purchases", domain: null}
    SR->>SO: run(query, domain=None)
    Note over SO: domain=None → search all registered domains (metadata + documents)

    SO->>IP: parse(query, all_registered_domain_configs)
    IP->>Haiku: combined intent prompt (both domain vocabularies)
    Haiku-->>IP: {type: DISCOVERY, entity_hint: Section, confidence: 0.88}
    IP-->>SO: ParsedIntent

    Note over SO: triple_search — no domain partition (all indices)
    par asyncio.gather
        SO->>VS: search(intent, top_k=10, domain=None)
        Note over VS: PGVector over all chunks (meta_ + doc_ prefixes)
        VS-->>SO: vector_results[10]
    and
        SO->>LS: search(intent, top_k=10, domain=None)
        Note over LS: Whoosh over both metadata/ and documents/ indices
        LS-->>SO: lucene_results[10]
    and
        SO->>GS: search(intent, top_k=10, domain=None)
        Note over GS: Cypher over both meta_* and doc_* labels
        GS-->>SO: graph_results[10]
    end

    SO->>AGG: run(all_results, top_k=10, domains=[fm, doc])
    Note over AGG: RRF merges across domains — doc_Section and meta_Account compete by rank
    AGG->>AGG: GraphBoost — neighbourhood within each domain separately
    AGG-->>SO: final_results[10] — likely dominated by doc_Section for this query

    SO->>SYN: synthesize(query, final_results, cross_domain=True)
    SYN-->>SO: "Found the capital expenditure approval policy:\nCapEx Policy Rev3 §4.2..."
    SO-->>SR: SearchState
    SR-->>Client: 200 SearchResponse(results, synthesis citing doc domain, latency_ms)
```

---

## 5. Re-Index Metadata (Manual Trigger)

```mermaid
sequenceDiagram
    participant Admin
    participant Router as IndexRouter
    participant IO as IngestionOrchestrator
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter
    participant XML as XMLFileConnector
    participant BG as BreadcrumbGenerator

    Admin->>Router: POST /domains/metadata/index
    Note over Router: optional body: {metadata_file: path} or {metadata_xml: raw_string}

    Router->>VI: clear_domain("metadata")
    Note over VI: deletes all chunks with domain_id='metadata' from PGVector table
    Router->>LI: wipe_index("metadata")
    Note over LI: deletes metadata/ Whoosh directory and recreates schema
    Note over GI: Neo4j uses MERGE — no wipe needed; stale nodes left in place

    Router->>IO: ingest_domain("metadata", IngestionMode.FULL)
    IO->>XML: fetch_all() — or fetch from supplied path/string

    loop each RawEntity
        XML-->>IO: RawEntity
        IO->>BG: generate(entity, METADATA_DOMAIN)
        BG-->>IO: MetadataChunk
        par fan-out
            IO->>VI: index([chunk])
            IO->>LI: index([chunk])
            IO->>GI: index([chunk]) — MERGE, idempotent
        end
    end

    IO->>GI: index_relationships(entities, METADATA_GRAPH_SCHEMA)
    IO-->>Router: IngestionResult(entities=N, chunks=N, duration_ms=...)
    Router-->>Admin: 200 IndexResponse(domain="metadata", entities_indexed=N, chunks_indexed=N, duration_ms=...)
```

---

## 6. LLM Fallback — Intent Heuristic

```mermaid
sequenceDiagram
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant LLM as Claude Haiku
    participant HF as HeuristicFallback

    SO->>IP: parse(query="SAAS_REVENUE", domain_config)
    IP->>LLM: POST /messages (intent prompt)
    
    alt LLM timeout or API error
        LLM-->>IP: ConnectTimeout / APIError
        IP->>HF: heuristic_fallback(query)
        HF->>HF: ALL_CAPS regex — [A-Z][A-Z0-9_]{2,}
        Note over HF: "SAAS_REVENUE" matches → LOOKUP
        HF-->>IP: ParsedIntent(LOOKUP, confidence=0.0, entity_hint=None)
    else LLM succeeds but confidence < 0.7
        LLM-->>IP: {type: DISCOVERY, confidence: 0.45}
        IP->>HF: heuristic_fallback(query)
        HF->>HF: no ALL_CAPS match; no traversal keywords
        Note over HF: "SAAS_REVENUE" ALL_CAPS pattern → LOOKUP
        HF-->>IP: ParsedIntent(LOOKUP, confidence=0.0)
    else LLM succeeds, confidence >= 0.7
        LLM-->>IP: {type: LOOKUP, confidence: 0.91}
        IP-->>SO: ParsedIntent(LOOKUP, confidence=0.91) — LLM result used
    end

    IP-->>SO: ParsedIntent — search continues regardless of path taken
    Note over SO: confidence=0.0 signals heuristic was used; search still runs
```
