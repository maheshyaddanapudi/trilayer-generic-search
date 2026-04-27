# MVP 06 — Entity Diagrams

---

## 1. Metadata — Core Entity Model

```mermaid
erDiagram
    Account {
        string code PK
        string desc
        string type
        string parent FK
        list   attributes
    }
    Level {
        string code PK
        string desc
    }
    Version {
        string code PK
        string desc
        date   start_time
        date   end_time
    }
    Sheet {
        string name PK
        string type
    }
    Dimension {
        string name PK
    }
    DimValue {
        string name      PK
        string value
        string dimension FK
    }

    Account     ||--o{ Account   : "PARENT_OF"
    Account     }o--o{ Account   : "LINKED_TO"
    Sheet       }o--o{ Account   : "INCLUDES_ACCOUNT"
    Sheet       }o--||  Version  : "USES_VERSION"
    Sheet       }o--||  Level    : "USES_LEVEL"
    Dimension   ||--o{ DimValue  : "HAS_VALUE"
```

Concrete sample data from `sample_metadata.xml`:

```
Accounts:     REVENUE → PROD_REVENUE → SAAS_REVENUE / LICENSE_REVENUE
              REVENUE → SVC_REVENUE
              COGS → DIRECT_MATERIAL → RAW_MATERIALS / SUPPLIES
              COGS → DIRECT_LABOR → MFG_LABOR / CONTRACT_LABOR
              GROSS_PROFIT (formula: REVENUE - COGS)
              NET_INCOME   (formula: GROSS_PROFIT - OPEX)

Linked pairs: REVENUE ↔ COGS, GROSS_PROFIT ↔ OPEX, SAAS_REVENUE ↔ HC_EXPENSE

Versions:     ACTUAL (2026-Q1), BUDGET (FY2026), Q2_FORECAST

Levels:       CORPORATE, DIVISION, DEPARTMENT

Sheets:       PL_Summary (standard), Revenue_Detail (cube), COGS_Detail (standard)

Dimensions:   Region → NA / EMEA / APAC
              Product → ENTERPRISE / SMB / STARTUP
              Department → ENGINEERING / SALES / MARKETING / FINANCE / OPS
```

---

## 2. Metadata — Neo4j Graph Model

```mermaid
erDiagram
    meta_Account {
        string code
        string desc
        string type
    }
    meta_Level {
        string code
        string desc
    }
    meta_Version {
        string code
        string desc
        date   start_time
        date   end_time
    }
    meta_Sheet {
        string name
        string type
    }
    meta_Dimension {
        string name
    }
    meta_DimValue {
        string name
        string value
    }

    meta_Account   ||--o{ meta_Account   : "PARENT_OF"
    meta_Account   }o--o{ meta_Account   : "LINKED_TO"
    meta_Sheet     }o--o{ meta_Account   : "INCLUDES_ACCOUNT"
    meta_Sheet     ||--o{ meta_Version   : "USES_VERSION"
    meta_Sheet     ||--o{ meta_Level     : "USES_LEVEL"
    meta_Dimension ||--o{ meta_DimValue  : "HAS_VALUE"
```

Neo4j label prefix `meta_` isolates all metadata nodes from the documents domain.
All writes use Cypher `MERGE` — safe for re-indexing without duplicate nodes.

---

## 3. Document Domain — Core Entity Model

```mermaid
erDiagram
    Document {
        string doc_id        PK
        string title
        string doc_type
        string status
        date   effective_date
        string owner
        string version
        list   tags
    }
    Section {
        string section_id    PK
        string doc_id        FK
        string heading
        int    order_index
        string content_summary
        int    page_number
    }

    Document ||--o{ Section  : "HAS_SECTION"
    Document ||--o{ Document : "SUPERSEDES"
```

Concrete breadcrumb examples:

```
Capital Expenditure Policy Rev3 | Document | Financial Policies |
  Corporate CapEx approval policy | owner=CFO Office; effective=2026-01-01; published

CapEx Policy Rev3 §4.2 | Section | doc:Capital Expenditure Policy Rev3 |
  Any CapEx over $50k requires CFO sign-off within 5 days | owner=CFO Office; page=8
```

---

## 4. Document Domain — Neo4j Graph Model

```mermaid
erDiagram
    doc_Document {
        string doc_id
        string title
        string doc_type
        string status
        date   effective_date
        string owner
    }
    doc_Section {
        string section_id
        string heading
        int    order_index
        int    page_number
    }
    doc_Tag {
        string name
    }

    doc_Document ||--o{ doc_Section  : "HAS_SECTION"
    doc_Document ||--o{ doc_Document : "SUPERSEDES"
    doc_Document }o--o{ doc_Tag      : "TAGGED_WITH"
```

Neo4j label prefix `doc_` isolates document nodes from the metadata domain.
`SUPERSEDES` enables lineage queries: "what did this policy replace?"
`TAGGED_WITH` enables tag-based graph traversal.

---

## 5. Core Data Models — System-Wide Flow

These models flow through the ingestion and search pipelines across both domains.

```mermaid
erDiagram
    RawEntity {
        string   entity_id
        string   entity_type
        string   domain_id
        string   name
        string   description
        dict     properties
        string   parent_id
        list     relationships
        datetime ingested_at
    }
    MetadataChunk {
        string chunk_id
        string domain_id
        string entity_id
        string entity_type
        string breadcrumb
        list   embedding
        dict   properties
        datetime created_at
    }
    SearchResult {
        string chunk_id
        float  score
        string breadcrumb
        string entity_id
        string entity_type
        string domain_id
        int    rank
        string source
    }
    ParsedIntent {
        string query_type
        string expanded_query
        string entity_hint
        dict   scope_filters
        float  confidence
        list   cypher_hints
    }
    SearchState {
        string query
        string domain
        ParsedIntent intent
        list   vector_results
        list   lucene_results
        list   graph_results
        list   final_results
        string synthesis
        float  latency_ms
    }

    RawEntity      ||--o{ MetadataChunk : "produces via BreadcrumbGenerator"
    MetadataChunk  ||--o{ SearchResult  : "returned as"
    ParsedIntent   ||--||  SearchState  : "stored in"
    SearchState    ||--o{ SearchResult  : "final_results"
```

---

## 6. API Request / Response Models

```mermaid
erDiagram
    SearchRequest {
        string query
        string domain
        int    top_k
        string search_mode
    }
    SearchResponse {
        string query
        string domain
        list   results
        string synthesis
        dict   intent
        float  latency_ms
    }
    FileUploadResponse {
        string doc_id
        string title
        int    sections_indexed
        int    vector_docs
        int    lucene_docs
        int    graph_nodes
        float  duration_ms
        int    file_size_bytes
    }
    IndexRequest {
        string metadata_file
        string metadata_xml
    }
    IndexResponse {
        string domain
        int    entities_indexed
        int    chunks_indexed
        float  duration_ms
    }
    HealthResponse {
        string status
        bool   neo4j_ok
        bool   vector_ok
        bool   lucene_ok
        int    metadata_chunks
        int    document_chunks
        float  uptime_seconds
    }

    SearchResponse ||--o{ SearchResult : "results list"
```

---

## 7. Domain Config Composition

```mermaid
erDiagram
    DomainConfig {
        string domain_id
        string display_name
        string description
        int    rrf_k
        float  graph_boost_factor
        int    graph_boost_top_n
        int    default_top_k
        bool   namespace_isolated
    }
    SourceConnector {
        string connector_type
        bool   supports_incremental
    }
    EntityTypeRegistry {
        dict entity_types
    }
    GraphSchema {
        string domain_namespace
        dict   node_labels
        list   relationships
        list   traversal_rules
        list   boost_edges
    }
    BreadcrumbTemplate {
        int    max_total_length
        int    lineage_depth
        string separator
    }
    IntentPromptConfig {
        dict entity_type_descriptions
        dict synonym_expansion_map
        dict query_type_examples
        dict cypher_hint_patterns
        string grounding_format_description
    }
    TriggerConfig {
        string mode
        bool   full_reindex_on_startup
    }

    DomainConfig ||--|| SourceConnector    : "connector"
    DomainConfig ||--|| EntityTypeRegistry : "entity_types"
    DomainConfig ||--|| GraphSchema        : "graph_schema"
    DomainConfig ||--|| BreadcrumbTemplate : "breadcrumb_template"
    DomainConfig ||--|| IntentPromptConfig : "intent_prompt"
    DomainConfig ||--|| TriggerConfig      : "trigger_config"
```
