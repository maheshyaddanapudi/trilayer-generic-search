# 07 — Sequence Diagrams

---

## 1. Domain Registration

```mermaid
sequenceDiagram
    actor Admin
    participant API as FastAPI
    participant DR as DomainRegistry
    participant IO as IngestionOrchestrator
    participant SC as SourceConnector
    participant BG as BreadcrumbGenerator
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter

    Admin->>API: POST /domains/register (DomainConfig payload)
    API->>DR: registry.register(config)
    DR->>DR: validate config (entity types, graph schema)
    DR-->>API: registered OK

    alt TriggerConfig.full_reindex_on_startup = true
        API->>IO: ingest_domain(domain_id, FULL)
        IO->>SC: connector.connect()
        SC-->>IO: connected

        loop for each RawEntity batch
            IO->>SC: connector.fetch_all()
            SC-->>IO: Iterator[RawEntity]
            IO->>BG: generate(entity, domain_id)
            BG->>GI: get_ancestors(entity_id, domain_id)
            GI-->>BG: ancestor chain
            BG-->>IO: MetadataChunk

            par Fan-out to all indices
                IO->>VI: index(chunks_batch)
                VI-->>IO: count
            and
                IO->>LI: index(chunks_batch)
                LI-->>IO: count
            and
                IO->>GI: index(chunks_batch)
                GI-->>IO: count
            end
        end

        IO->>SC: connector.disconnect()
        IO-->>API: IngestionResult (counts + duration)
    end

    API-->>Admin: 201 Created + IngestionResult
```

---

## 2. Full Batch Ingestion

```mermaid
sequenceDiagram
    actor Caller
    participant API as FastAPI
    participant IO as IngestionOrchestrator
    participant SC as SourceConnector
    participant BG as BreadcrumbGenerator
    participant CD as ChangeDetector
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter

    Caller->>API: POST /domains/{id}/index (mode=full)
    API->>IO: ingest_domain(domain_id, FULL)

    IO->>VI: clear(domain_id)
    IO->>LI: clear(domain_id)
    IO->>GI: clear(domain_id)

    IO->>SC: connect()
    IO->>SC: fetch_all()

    loop batches of 100 entities
        SC-->>IO: [RawEntity, ...]
        IO->>BG: generate(entity, domain_id) for each
        BG-->>IO: [MetadataChunk, ...]

        par
            IO->>VI: index(chunks)
        and
            IO->>LI: index(chunks)
        and
            IO->>GI: index(chunks)
            IO->>GI: index_relationships(relationships, schema)
        end
    end

    IO->>SC: disconnect()
    IO-->>API: IngestionResult
    API-->>Caller: 200 OK + IngestionResult
```

---

## 3. On-Upload File Indexing

```mermaid
sequenceDiagram
    actor User
    participant API as FastAPI
    participant FSC as FileSystemConnector
    participant IO as IngestionOrchestrator
    participant BG as BreadcrumbGenerator
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter

    User->>API: POST /domains/{id}/files/upload (binary file)
    API->>FSC: process_upload(file_bytes, filename, mime_type)

    FSC->>FSC: extract text (pdfminer / python-docx / openpyxl)
    FSC->>FSC: detect sections / headings
    FSC-->>API: Iterator[RawEntity] (one per section)

    API->>IO: ingest_entities(entities, domain_id)

    loop for each section entity
        IO->>BG: generate(entity, domain_id)
        BG-->>IO: MetadataChunk

        par
            IO->>VI: index([chunk])
        and
            IO->>LI: index([chunk])
        and
            IO->>GI: index([chunk])
        end
    end

    IO-->>API: IngestionResult
    API-->>User: 200 OK (file immediately searchable)

    Note over API,GI: Target: < 10s for 50-page PDF
```

---

## 4. Real-Time CDC Update (Incremental)

```mermaid
sequenceDiagram
    participant SRC as Source System
    participant ESC as EventStreamConnector
    participant IO as IngestionOrchestrator
    participant CD as ChangeDetector
    participant BG as BreadcrumbGenerator
    participant VI as VectorIndexWriter
    participant LI as LuceneIndexWriter
    participant GI as GraphIndexWriter

    SRC->>ESC: ChangeEvent (UPDATE entity_id=REVENUE)
    ESC->>IO: handle_change_event(event)

    IO->>CD: classify(event)
    CD-->>IO: UPDATE

    IO->>SC: fetch_since(last_checkpoint) for entity_id
    SC-->>IO: updated RawEntity

    IO->>BG: generate(entity, domain_id)
    BG->>GI: get_ancestors(entity_id, domain_id)
    GI-->>BG: ancestors
    BG-->>IO: updated MetadataChunk

    par Update all indices
        IO->>VI: delete([old_chunk_id])
        IO->>VI: index([new_chunk])
    and
        IO->>LI: delete([old_chunk_id])
        IO->>LI: index([new_chunk])
    and
        IO->>GI: index([new_chunk])
    end

    IO->>CD: propagate_to_neighbours(entity_id, domain_id, graph_writer)
    CD->>GI: get_neighbours(entity_id, depth=1)
    GI-->>CD: [child_entity_ids]

    loop for each affected child
        CD->>IO: ingest_entities([child_entity], domain_id)
    end

    Note over IO,GI: Target: < 5s end-to-end
```

---

## 5. Single-Domain Search (Full Pipeline)

```mermaid
sequenceDiagram
    actor User
    participant API as FastAPI
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant LLM1 as Claude (Haiku)
    participant VS as VectorSearch
    participant LS as LuceneSearch
    participant GS as GraphSearch
    participant AGG as AggregationPipeline
    participant SYN as Synthesizer
    participant LLM2 as Claude (Sonnet)

    User->>API: POST /search {query, domain, screen_context}
    API->>SO: run(query, domain, screen_context)

    Note over SO: LangGraph State: START

    SO->>IP: parse(query, domain, screen_context)
    IP->>IP: build_system_prompt(domain_config + screen_context)
    IP->>LLM1: complete(prompt, system)
    LLM1-->>IP: JSON {query_type, entities, expanded_terms, cypher_hint}
    IP->>IP: _parse_llm_response(json)
    IP-->>SO: ParsedIntent

    Note over SO: LangGraph State: parse_intent → tri_search

    par Parallel tri-dispatch
        SO->>VS: search(intent, top_k)
        VS->>VS: encode(entities + expanded_terms)
        VS->>VS: faiss_index.search(vector, top_k)
        VS-->>SO: [SearchResult x top_k]
    and
        SO->>LS: search(intent, top_k)
        LS->>LS: build_bm25_query(entities)
        LS->>LS: whoosh_searcher.search(query)
        LS-->>SO: [SearchResult x top_k]
    and
        SO->>GS: search(intent, top_k)
        alt cypher_hint present
            GS->>GS: neo4j_driver.run(cypher_hint)
        else entity lookup
            GS->>GS: neo4j_driver.run(entity_lookup_cypher)
        end
        GS-->>SO: [SearchResult x top_k]
    end

    Note over SO: LangGraph State: tri_search → aggregate

    SO->>AGG: run({vector, lucene, graph}, top_k, config)
    AGG->>AGG: RRFAggregator.process(results)
    AGG->>AGG: GraphBoostingAggregator.process(rrf_results)
    AGG-->>SO: [SearchResult x top_k merged + boosted]

    Note over SO: LangGraph State: aggregate → synthesize

    SO->>SYN: synthesize(query, top_chunks, domain_config)
    SYN->>SYN: build_breadcrumb_context(chunks)
    SYN->>LLM2: complete(breadcrumbs + query, grounding_system_prompt)
    LLM2-->>SYN: grounded natural language answer
    SYN-->>SO: synthesis string

    Note over SO: LangGraph State: synthesize → END

    SO-->>API: SearchState (results + synthesis + latency)
    API-->>User: SearchResponse
```

---

## 6. Multi-Domain Search

```mermaid
sequenceDiagram
    actor User
    participant API as FastAPI
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant DR as DomainRouter
    participant DA as Domain A SearchOrchestrator
    participant DB as Domain B SearchOrchestrator
    participant DN as Domain N SearchOrchestrator
    participant XAGG as Cross-Domain Aggregator
    participant SYN as Synthesizer

    User->>API: POST /search {query} (no domain specified)
    API->>SO: run(query, domain=None)

    SO->>IP: parse(query, domain=None)
    IP-->>SO: ParsedIntent (target_domain=None OR inferred)

    SO->>DR: route(intent, registered_domains)
    DR->>DR: score each domain's relevance to intent
    DR-->>SO: [domain_a, domain_b, domain_n] (ordered by relevance)

    par Search each domain independently
        SO->>DA: run(query, domain="financial_metadata")
        DA-->>SO: SearchState_A (results + synthesis)
    and
        SO->>DB: run(query, domain="documents")
        DB-->>SO: SearchState_B
    and
        SO->>DN: run(query, domain="compliance")
        DN-->>SO: SearchState_N
    end

    SO->>XAGG: cross_domain_rrf([results_A, results_B, results_N])
    Note over XAGG: Each domain's results are weighted by<br/>domain relevance score from DomainRouter
    XAGG-->>SO: merged cross-domain results

    SO->>SYN: synthesize(query, merged_chunks, domains=[A,B,N])
    Note over SYN: Breadcrumbs carry domain label in lineage<br/>LLM cites "In financial_metadata: ..." / "In documents: ..."
    SYN-->>SO: multi-domain grounded answer

    SO-->>API: SearchState
    API-->>User: SearchResponse (results span domains)
```

---

## 7. Screen Context Search

```mermaid
sequenceDiagram
    actor User as User (in Workday UI)
    participant UI as Frontend
    participant API as FastAPI
    participant IP as IntentParser
    participant LLM as Claude (Haiku)
    participant SO as SearchOrchestrator

    Note over User,UI: User is viewing P&L sheet:<br/>Accounts: COGS, REVENUE<br/>Version: ACTUAL, Level: DIVISION

    User->>UI: types "why is this high?"
    UI->>UI: capture screen_context from current view
    Note right of UI: screen_context = {<br/>  visible_accounts: ["COGS","REVENUE"],<br/>  active_version: "ACTUAL",<br/>  active_level: "DIVISION",<br/>  time_period: "Q1_2026"<br/>}

    UI->>API: POST /search {query: "why is this high?", screen_context: {...}}
    API->>IP: parse(query, domain="financial_metadata", screen_context)

    IP->>IP: inject screen_context into system prompt
    Note right of IP: "The user is currently viewing:<br/>Accounts: COGS, REVENUE<br/>Version: ACTUAL, Level: DIVISION<br/>Interpret 'this' as COGS in ACTUAL"

    IP->>LLM: complete(enriched_prompt)
    LLM-->>IP: {query_type: "discovery", entities: ["COGS"], structural_filter: "ACTUAL/DIVISION scope"}
    IP-->>API: ParsedIntent (COGS-scoped, ACTUAL version, DIVISION level)

    API->>SO: run(query, intent=scoped_intent)
    Note over SO: Search runs with COGS as primary entity,<br/>scoped to ACTUAL + DIVISION
    SO-->>API: SearchState (results focused on COGS components)
    API-->>UI: SearchResponse
    UI-->>User: "COGS is high because DIRECT_LABOR increased..."
```

---

## 8. LLM Fallback (Heuristic)

```mermaid
sequenceDiagram
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant LLM as Claude
    participant HE as HeuristicEngine

    SO->>IP: parse("show children of REVENUE")
    IP->>LLM: complete(prompt, system)

    alt LLM call succeeds
        LLM-->>IP: valid JSON
        IP->>IP: _parse_llm_response(json)
        IP-->>SO: ParsedIntent (confidence=1.0)
    else LLM call fails or returns malformed JSON
        LLM-->>IP: error / bad JSON
        IP->>HE: _heuristic_fallback(query)
        HE->>HE: detect traversal keywords ("children")
        HE->>HE: extract ALL_CAPS entities (["REVENUE"])
        HE->>HE: expand known synonyms
        HE-->>IP: ParsedIntent (confidence=0.0)
        IP-->>SO: ParsedIntent (confidence=0.0, query_type=TRAVERSAL)
        Note over SO: Search continues with heuristic intent<br/>Pipeline never hard-fails at this stage
    end
```

---

## 9. Session Creation and Context Injection

```mermaid
sequenceDiagram
    actor User as User / Frontend
    participant API as FastAPI
    participant SREG as SessionRegistry
    participant GI as GraphIndexWriter
    participant VI as VectorIndexWriter

    User->>API: POST /sessions
    API->>SREG: create_session()
    SREG-->>API: session_id = "abc123"
    API-->>User: { "session_id": "abc123" }

    Note over User,VI: User is now on the P&L screen.<br/>Frontend sends screen context.

    User->>API: POST /sessions/abc123/context\n{ type: "screen_context",\n  visible_accounts: ["COGS","REVENUE"],\n  active_version: "ACTUAL" }

    API->>SREG: materialise_screen_context(session_id, screen_context, "financial_metadata", graph_writer)

    loop for each visible entity
        SREG->>VI: get_chunk("financial_metadata::Account::COGS")
        VI-->>SREG: MetadataChunk (breadcrumb + embedding)
        SREG->>SREG: create SessionChunk\n  linked_permanent_ids=["financial_metadata::Account::COGS"]\n  source_type=SCREEN_CONTEXT\n  ttl=1800s
    end

    SREG-->>API: [SessionChunk x2]
    API-->>User: { "chunks_created": 2, "ttl_seconds": 1800 }

    Note over User,VI: Later — user injects a live API response mid-session.

    User->>API: POST /sessions/abc123/context\n{ type: "api_response",\n  data: { COGS_actual: 4200000 },\n  linked_ids: ["financial_metadata::Account::COGS"] }

    API->>SREG: inject_api_response(session_id, data, domain,\n  "COGS actual value Q1 2026",\n  linked_permanent_ids=["financial_metadata::Account::COGS"])
    SREG->>SREG: create SessionChunk\n  source_type=API_RESPONSE\n  breadcrumb="[LIVE] COGS | actual | Q1 2026 | $4.2M"
    SREG-->>API: SessionChunk
    API-->>User: { "chunk_id": "session::abc123::api_response::COGS", "ttl_seconds": 1800 }
```

---

## 10. Session-Aware Search (Quad-Dispatch)

```mermaid
sequenceDiagram
    actor User
    participant API as FastAPI
    participant SO as SearchOrchestrator
    participant IP as IntentParser
    participant SREG as SessionRegistry
    participant VS as VectorSearch
    participant LS as LuceneSearch
    participant GS as GraphSearch
    participant SS as SessionSearch
    participant AGG as AggregationPipeline
    participant SYN as Synthesizer

    User->>API: POST /search\n{ query: "why is this high?",\n  session_id: "abc123",\n  screen_context: { visible: ["COGS"] } }

    API->>SO: run(query, session_id="abc123", screen_context={...})

    SO->>SREG: materialise_screen_context("abc123", screen_context)
    Note over SREG: Creates/updates session chunks<br/>for COGS (already exists from earlier POST)

    SO->>IP: parse(query, session_id="abc123", screen_context)
    Note over IP: Screen context injected into prompt.<br/>"this" resolved to COGS in ACTUAL.
    IP-->>SO: ParsedIntent { entities: ["COGS"], structural_filter: "ACTUAL" }

    par Quad-dispatch
        SO->>VS: search(intent, top_k=10)
        VS-->>SO: vector_results (semantic matches for COGS)
    and
        SO->>LS: search(intent, top_k=10)
        LS-->>SO: lucene_results (exact COGS + sub-accounts)
    and
        SO->>GS: search(intent, top_k=10)
        GS-->>SO: graph_results (COGS + DIRECT_MATERIAL + DIRECT_LABOR)
    and
        SO->>SS: search(intent, top_k=10, session_id="abc123")
        SS->>SREG: get_chunks("abc123")
        SREG-->>SS: [COGS screen chunk, COGS live API chunk ($4.2M)]
        SS->>SS: cosine similarity scan
        SS-->>SO: session_results (both session chunks, high score)
    end

    SO->>AGG: run({vector, lucene, graph, session}, top_k=10)

    AGG->>AGG: RRFAggregator: merge 4 lists
    AGG->>AGG: GraphBoostingAggregator: boost DIRECT_MATERIAL, DIRECT_LABOR
    AGG->>AGG: SessionLinkBoostingAggregator:\n  COGS session chunks link to permanent COGS chunk\n  → COGS permanent chunk gets 1.3× boost
    AGG-->>SO: merged_results (COGS + sub-accounts ranked high)

    SO->>SYN: synthesize(query, chunks, session_chunks)
    Note over SYN: Synthesis prompt includes:<br/>- Permanent breadcrumbs (indexed data)<br/>- Session chunks labelled [LIVE]<br/>"COGS actual Q1 2026: $4.2M"
    SYN-->>SO: "COGS is high primarily due to increased DIRECT_LABOR\ncosts (up 18% vs budget). Live data shows Q1 COGS\nat $4.2M vs $3.6M budget [LIVE: session context]."

    SO-->>API: SearchState
    API-->>User: SearchResponse (synthesis cites both indexed + live data)
```
