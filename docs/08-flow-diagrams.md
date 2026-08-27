# 08 — Flow Diagrams

---

## 1. Write Path — Full Ingestion Pipeline

```mermaid
flowchart TD
    A([Trigger]) --> B{Trigger source}
    B -->|POST /index| C[Manual full re-index]
    B -->|Startup + full_reindex=true| C
    B -->|Cron schedule| D[Incremental fetch_since checkpoint]
    B -->|CDC event| E[Single entity update]
    B -->|File upload| F[File processing pipeline]

    C --> G[clear all indices for domain]
    G --> H[connector.connect]
    D --> H
    H --> I[fetch_all / fetch_since → RawEntity stream]

    I --> J[BreadcrumbGenerator.generate]
    J --> K{Entity has parent?}
    K -->|yes| L[GraphIndexWriter.get_ancestors\nbuild lineage chain]
    K -->|no| M[root-level breadcrumb]
    L --> N[TemplateBreadcrumbTemplate.generate\nbreadcrumb string]
    M --> N

    N --> O[MetadataChunk ready]
    O --> P[Batch accumulator\n100 chunks]
    P --> Q{Batch full or\nstream exhausted?}
    Q -->|no| I
    Q -->|yes| R[Fan-out to all three writers]

    R --> S[VectorIndexWriter.index\nencode breadcrumbs → FAISS]
    R --> T[LuceneIndexWriter.index\ntokenize → Whoosh]
    R --> U[GraphIndexWriter.index\nMERGE nodes + edges → Neo4j]

    S --> V{More batches?}
    T --> V
    U --> V
    V -->|yes| I
    V -->|no| W[connector.disconnect]
    W --> X[IngestionResult\ncounts + duration + errors]
    X --> Y([Done])

    E --> Z[ChangeDetector.classify event]
    Z --> AA{Event type}
    AA -->|ADD| AB[generate chunk + write all indices]
    AA -->|UPDATE| AC[delete old chunk + generate new + write all]
    AA -->|DELETE| AD[delete from all indices]
    AC --> AE[NeighbourPropagator\nre-index affected children]
    AB --> Y
    AE --> Y
    AD --> Y

    F --> AF[FileSystemConnector.process_upload\ntext extract → section detection]
    AF --> AG[Yields RawEntity per section]
    AG --> J
```

---

## 2. Read Path — Query Pipeline

```mermaid
flowchart TD
    A([User submits query]) --> B[FastAPI POST /search]
    B --> C{Domain specified\nin request?}

    C -->|yes| D[Single-domain mode]
    C -->|no| E[Multi-domain mode\nfan-out to all registered domains]

    D --> F[Load DomainConfig\nfrom DomainRegistry]
    E --> G[Load all DomainConfigs\norder by estimated relevance]

    F --> H[IntentParser.parse\nquery + domain + screen_context]
    G --> H

    H --> I[Build system prompt\nfrom IntentPromptConfig]
    I --> J[Claude Haiku\nJSON intent extraction]
    J --> K{LLM succeeded?}
    K -->|yes| L[ParsedIntent confidence=1.0]
    K -->|no| M[Heuristic fallback\nconfidence=0.0]
    L --> N
    M --> N

    N[ParsedIntent ready] --> O[asyncio.gather\ntri-dispatch in parallel]

    O --> P[VectorSearch.search\nencode query → ANN lookup → FAISS]
    O --> Q[LuceneSearch.search\nBM25 keyword match → Whoosh]
    O --> R[GraphSearch.search\nCypher traversal OR entity lookup → Neo4j]
    O --> RS[SessionSearch.search\ncosine scan → SessionRegistry]

    P --> S[vector_results list]
    Q --> T[lucene_results list]
    R --> U[graph_results list]
    RS --> US[session_results list]

    S --> V[AggregationPipeline.run]
    T --> V
    U --> V
    US --> V

    V --> W[RRFAggregator\ncombine 4 ranked lists]
    W --> X[GraphBoostingAggregator\nboost neighbours of top Lucene hits]
    X --> XS[SessionLinkBoostingAggregator\nboost permanents linked from session chunks]
    XS --> Y[merged_results sorted by score]

    Y --> Z[Synthesizer.synthesize\ntop-K breadcrumbs → Claude Sonnet]
    Z --> AA[Grounded NL answer\ncitations only from retrieved chunks]

    AA --> AB[SearchResponse\nresults + synthesis + latency]
    AB --> AC([Return to user])
```

---

## 3. Intent Classification Decision Tree

```mermaid
flowchart TD
    A([Raw user query]) --> B[LLM attempt:\nClaude Haiku with domain prompt]

    B --> C{LLM returned\nvalid JSON?}
    C -->|yes| D[Use LLM classification]
    C -->|no| E[Heuristic fallback]

    D --> F{query_type field}
    F -->|lookup| G[LOOKUP]
    F -->|traversal| H[TRAVERSAL]
    F -->|discovery| I[DISCOVERY]
    F -->|unknown| I

    E --> J{Contains traversal\nkeywords?}
    J -->|children/parent/hierarchy\n/lineage/breakdown| H
    J -->|no| K{Contains ALL_CAPS\nidentifier regex?}
    K -->|yes| G
    K -->|no| I

    G --> L[Index emphasis:\nLucene primary\nVector + Graph secondary]
    H --> M[Index emphasis:\nGraph primary\nVector + Lucene for candidates]
    I --> N[Index emphasis:\nVector primary\nLucene + Graph secondary]

    L --> O[ParsedIntent with query_type=LOOKUP]
    M --> P[ParsedIntent with query_type=TRAVERSAL\n+ cypher_hint if available]
    N --> Q[ParsedIntent with query_type=DISCOVERY]
```

---

## 4. RRF + Graph Boost Aggregation

```mermaid
flowchart TD
    A([3 result lists:\nvector_results\nlucene_results\ngraph_results]) --> B[RRFAggregator]

    B --> C{For each unique\nchunk_id across all lists}
    C --> D[Calculate RRF score:\nscore += 1 / 60 + rank_i\nfor each list containing it]
    D --> E[Sort all chunks by RRF score descending]
    E --> F[merged_list top-K]

    F --> G[GraphBoostingAggregator]
    G --> H[Take top-N Lucene results\ndefault N=3\nhighest-precision exact matches]

    H --> I[GraphIndexWriter.get_neighbours\nfetch 1-hop graph neighbours\nusing domain boost_edges]
    I --> J[neighbour_ids set]

    J --> K{For each item\nin merged_list}
    K --> L{item.chunk_id\nin neighbour_ids?}
    L -->|yes| M[Apply boost_factor multiplier\ndefault 1.5×\nmark boost_applied=True]
    L -->|no| N[Score unchanged]
    M --> O
    N --> O

    O{More items?} -->|yes| K
    O -->|no| P[Re-sort merged_list\nby boosted scores]
    P --> Q([Final ranked list\nto Synthesizer])
```

---

## 5. Domain Routing (Multi-Domain)

```mermaid
flowchart TD
    A([Query with no domain specified]) --> B[IntentParser.parse\nwithout domain constraint]

    B --> C[ParsedIntent\ntarget_domain=None]

    C --> D[DomainRouter.route\nintent + registered domains list]

    D --> E{Intent contains\nexplicit domain signals?}
    E -->|yes e.g. entity matches\none domain's vocabulary| F[Score that domain highest\nroute to it primarily]
    E -->|no| G[Score ALL domains\nby vocabulary overlap]

    G --> H{Score threshold\nmet by multiple domains?}
    H -->|one domain clearly wins| F
    H -->|multiple domains score high| I[Fan-out search\nto top-M domains]

    F --> J[Single domain search path]
    I --> K[Parallel per-domain\nSearchOrchestrator.run]

    K --> L[Cross-domain RRF merge\nweighted by domain relevance score]
    J --> M[Standard RRF + boost\nwithin domain]

    L --> N[Cross-domain merged results]
    M --> O[Single-domain merged results]

    N --> P[Synthesizer with multi-domain context\nbreadcrumbs carry domain in lineage]
    O --> Q[Synthesizer with single-domain context]

    P --> R([SearchResponse\nresults tagged with source domain])
    Q --> R
```

---

## 6. Screen Context Injection Flow

```mermaid
flowchart TD
    A([Search request with screen_context]) --> B{screen_context\npresent?}

    B -->|no| C[Standard intent parsing\nno context injection]
    B -->|yes| D[ScreenContextProcessor]

    D --> E[Extract visible entities\nfrom screen_context]
    D --> F[Extract active filters\nversion / level / time period]
    D --> G[Infer implicit scope\ne.g. current sheet]

    E --> H[Append to intent.entities]
    F --> I[Set intent.structural_filter\ne.g. 'ACTUAL version, DIVISION level']
    G --> J[Set intent.domain_context]

    H --> K[Enriched system prompt\nfor IntentParser]
    I --> K
    J --> K

    K --> L[Claude Haiku\nscope-aware intent extraction]
    L --> M[ParsedIntent with screen scope]

    M --> N[Tri-dispatch scoped\nto visible entities + filters]
    N --> O{Graph search:\nscope to screen entities first\nthen expand}
    N --> P{Vector search:\nweight screen entities in query text}
    N --> Q{Lucene search:\nrequire domain filter from screen}

    O --> R[Aggregation]
    P --> R
    Q --> R
    R --> S([Results grounded in\nwhat the user can see])
```

---

## 7. File Upload to Indexed (End-to-End)

```mermaid
flowchart TD
    A([File upload: PDF / DOCX / XLSX]) --> B[POST /domains/documents/files/upload]

    B --> C[MIME type validation]
    C --> D{Supported type?}
    D -->|no| E([400 Unsupported file type])
    D -->|yes| F[Store in domain file directory]

    F --> G[FileSystemConnector.process_upload]
    G --> H{File type}
    H -->|PDF| I[pdfminer text extraction]
    H -->|DOCX| J[python-docx extraction]
    H -->|XLSX| K[openpyxl extraction]

    I --> L[Section detector\nheading heuristics]
    J --> L
    K --> M[Sheet/row → structured entity]

    L --> N[RawEntity per section\nwith doc title as parent]
    M --> N

    N --> O[BreadcrumbGenerator\nfor each section entity]
    O --> P[MetadataChunk with\nbreadcrumb: Title | Section | Doc | Summary | Tags]

    P --> Q[IngestionOrchestrator.ingest_entities]
    Q --> R[Fan-out to all three indices]

    R --> S[VectorIndexWriter: embed section breadcrumb]
    R --> T[LuceneIndexWriter: tokenize section breadcrumb]
    R --> U[GraphIndexWriter: doc→section nodes + HAS_SECTION edges]

    S --> V[IngestionResult]
    T --> V
    U --> V

    V --> W{background=false?}
    W -->|yes| X([Synchronous 200 OK + IngestionResult\nFile immediately searchable])
    W -->|no| Y([202 Accepted + job_id\nPoll GET /jobs/job_id for status])
```

---

## 8. Session Layer Participation in Aggregation

```mermaid
flowchart TD
    A([Quad-dispatch complete:\nvector_results\nlucene_results\ngraph_results\nsession_results]) --> B[RRFAggregator\ncombine all 4 lists]

    B --> C{session_results\nnon-empty?}
    C -->|no| D[Standard RRF score]
    C -->|yes| E[Session chunks included in RRF\nat their cosine similarity score]

    D --> F[GraphBoostingAggregator]
    E --> F

    F --> G[Boost graph neighbours\nof top Lucene hits]
    G --> H[SessionLinkBoostingAggregator]

    H --> I{Any session chunk has\nlinked_permanent_ids?}
    I -->|no| J[No session link boost applied]
    I -->|yes| K[Collect all linked permanent chunk_ids]

    K --> L{Each permanent chunk\nin merged_results?}
    L -->|yes| M[Apply session_link_boost_factor × rrf_score\nmark boost_applied=True, source=session_link]
    L -->|no| N[Skip — not in result set]

    M --> O[Re-sort all results by boosted score]
    N --> O
    J --> O

    O --> P[Final merged list]
    P --> Q[Synthesizer]

    Q --> R{Result contains\nsession chunks?}
    R -->|yes| S[Session chunks included in breadcrumb context\nlabelled as LIVE in synthesis prompt]
    R -->|no| T[Only permanent breadcrumbs]

    S --> U[LLM generates answer\nciting both indexed data\nand live session context]
    T --> V[LLM generates answer\nciting indexed data only]

    U --> W([SearchResponse\nresults + synthesis])
    V --> W
```

---

## 9. Session Lifecycle Flow

```mermaid
flowchart TD
    A([POST /sessions]) --> B[SessionRegistry.create_session\ngenerate UUID session_id]
    B --> C[Return session_id to client]

    C --> D{Client sends\nscreen_context?}
    D -->|yes| E[POST /sessions/id/context\ntype=screen_context]
    D -->|no| F[Client issues search with session_id]

    E --> G[SessionRegistry.materialise_screen_context\nlookup permanent chunks\ncreate SessionChunk per visible entity\nwith linked_permanent_ids]
    G --> F

    F --> H[SearchOrchestrator.run with session_id]
    H --> I[SessionSearch participates in quad-dispatch]
    I --> J[SessionLinkBoostingAggregator runs]
    J --> K[Results returned with session-boosted ranking]

    K --> L{Client injects\nlive API data?}
    L -->|yes| M[POST /sessions/id/context\ntype=api_response\nlinked_ids=[perm_chunk_ids]]
    L -->|no| N

    M --> N[Next search sees live API chunk\nin SessionSearch results]
    N --> O{Session idle\n> TTL seconds?}

    O -->|no| F
    O -->|yes| P[Background purge: SessionRegistry.purge_expired\nremove all session chunks]

    P --> Q([Session ended])

    F --> R{Client explicitly\nends session?}
    R -->|yes| S[DELETE /sessions/id\nSessionRegistry.end_session\nimmediate purge]
    S --> Q
    R -->|no| O
```
