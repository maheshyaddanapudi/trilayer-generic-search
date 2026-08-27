# 06 — Entity Diagrams

---

## 1. Canonical Data Model

The entities that flow through the framework, regardless of domain.

```mermaid
erDiagram
    DOMAIN_CONFIG {
        string domain_id PK
        string display_name
        string description
        int rrf_k
        float graph_boost_factor
        int graph_boost_top_n
        bool namespace_isolated
    }

    ENTITY_TYPE_DEFINITION {
        string name PK
        string domain_id FK
        string id_field
        string display_field
        string description_field
        string parent_type
    }

    PROPERTY_DEFINITION {
        string name PK
        string entity_type FK
        string field_type
        bool required
        bool searchable
    }

    RAW_ENTITY {
        string entity_id PK
        string domain FK
        string entity_type FK
        string name
        string description
        string parent_id
        string parent_type
        string source_url
        datetime last_modified
    }

    RAW_RELATIONSHIP {
        string source_id FK
        string target_id FK
        string relationship_type
        json properties
    }

    METADATA_CHUNK {
        string chunk_id PK
        string domain FK
        string element_id
        string element_type
        string name
        string description
        text breadcrumb
        json lineage_path
        json attributes
        string source_url
        vector embedding
    }

    SEARCH_RESULT {
        string chunk_id FK
        float score
        int rank
        json sources
        float rrf_score
        bool boost_applied
    }

    INGESTION_RESULT {
        string result_id PK
        string domain_id FK
        string mode
        int entities_processed
        int graph_nodes
        int vector_docs
        int lucene_docs
        float duration_ms
        json errors
        datetime checkpoint
    }

    CHANGE_EVENT {
        string event_id PK
        string domain FK
        string event_type
        string entity_id
        string entity_type
        json payload
        datetime timestamp
    }

    DOMAIN_CONFIG ||--o{ ENTITY_TYPE_DEFINITION : "declares"
    ENTITY_TYPE_DEFINITION ||--o{ PROPERTY_DEFINITION : "has"
    DOMAIN_CONFIG ||--o{ RAW_ENTITY : "owns"
    RAW_ENTITY ||--o{ RAW_RELATIONSHIP : "participates in"
    RAW_ENTITY ||--|| METADATA_CHUNK : "produces"
    METADATA_CHUNK ||--o{ SEARCH_RESULT : "returned as"
    DOMAIN_CONFIG ||--o{ INGESTION_RESULT : "tracks"
    DOMAIN_CONFIG ||--o{ CHANGE_EVENT : "receives"
    SESSION_CHUNK }o--o{ METADATA_CHUNK : "links to (permanent)"
```

---

## 5. Session Layer Data Model

```mermaid
erDiagram
    SESSION {
        string session_id PK
        datetime created_at
        datetime last_activity
        int chunk_count
    }

    SESSION_CHUNK {
        string chunk_id PK
        string session_id FK
        string source_type
        string domain
        string name
        string description
        text breadcrumb
        json attributes
        json linked_permanent_ids
        datetime created_at
        int ttl_seconds
    }

    METADATA_CHUNK {
        string chunk_id PK
        string domain
        string element_type
        string name
        text breadcrumb
    }

    SEARCH_RESULT_SESSION {
        string chunk_id FK
        float score
        int rank
        string source
        bool boost_applied
    }

    SESSION ||--o{ SESSION_CHUNK : "holds"
    SESSION_CHUNK }o--o{ METADATA_CHUNK : "linked_permanent_ids → chunk_id"
    SESSION_CHUNK ||--o{ SEARCH_RESULT_SESSION : "returned as"
```

### Session Source Types and Their Linked Permanent IDs

```
SessionSourceType        Example linked_permanent_ids
─────────────────        ─────────────────────────────────────────────
SCREEN_CONTEXT           ["financial_metadata::Account::COGS",
                          "financial_metadata::Account::REVENUE"]

API_RESPONSE             ["financial_metadata::Account::SAAS_REVENUE"]
(live balance data)

DYNAMIC_RESULT           chunk_ids from previous query's merged_results

USER_ANNOTATION          user-specified entity chunk_ids
("I'm working on EMEA")  ["financial_metadata::DimValue::EMEA"]
```

---

## 2. Neo4j Graph Node / Edge Model

The physical model inside Neo4j. Domain namespace is prefixed to all labels
(e.g., `financial_metadata_Account`, `hr_Employee`).

```mermaid
erDiagram
    GRAPH_NODE {
        string chunk_id PK
        string domain
        string element_id
        string element_type
        string name
        text breadcrumb
        json attributes
        datetime indexed_at
    }

    GRAPH_EDGE {
        string source_chunk_id FK
        string target_chunk_id FK
        string relationship_type
        json properties
        datetime created_at
    }

    GRAPH_NODE ||--o{ GRAPH_EDGE : "source of"
    GRAPH_NODE ||--o{ GRAPH_EDGE : "target of"
```

### Example: Financial Metadata Domain Graph

```mermaid
erDiagram
    ACCOUNT {
        string code PK
        string desc
        string type
        string parent_code FK
        json attributes
    }

    LEVEL {
        string code PK
        string desc
    }

    VERSION {
        string code PK
        string desc
        date start_time
        date end_time
    }

    SHEET {
        string name PK
        string type
    }

    DIMENSION {
        string name PK
    }

    DIM_VALUE {
        string name PK
        string dimension FK
        string value
    }

    TIME_POINT {
        string code PK
        date value
    }

    ACCOUNT ||--o{ ACCOUNT : "PARENT_OF"
    ACCOUNT ||--o{ ACCOUNT : "LINKED_TO"
    SHEET ||--o{ ACCOUNT : "INCLUDES_ACCOUNT"
    SHEET ||--o{ VERSION : "USES_VERSION"
    SHEET ||--o{ LEVEL : "USES_LEVEL"
    DIMENSION ||--o{ DIM_VALUE : "HAS_VALUE"
```

### Example: HR Domain Graph

```mermaid
erDiagram
    EMPLOYEE {
        string employee_id PK
        string name
        string title
        string level
        string location
        string manager_id FK
    }

    DEPARTMENT {
        string dept_id PK
        string name
        string parent_dept_id FK
    }

    ROLE {
        string role_id PK
        string title
        string job_family FK
        string level_band
    }

    JOB_FAMILY {
        string family_id PK
        string name
        string track
    }

    COMPETENCY {
        string comp_id PK
        string name
        string category
    }

    EMPLOYEE ||--o{ EMPLOYEE : "REPORTS_TO"
    EMPLOYEE }o--|| DEPARTMENT : "BELONGS_TO"
    EMPLOYEE }o--|| ROLE : "FILLED_BY"
    DEPARTMENT ||--o{ DEPARTMENT : "PARENT_OF"
    ROLE }o--|| JOB_FAMILY : "BELONGS_TO_FAMILY"
    ROLE ||--o{ COMPETENCY : "REQUIRES"
```

### Example: Compliance Domain Graph

```mermaid
erDiagram
    CONTROL {
        string control_id PK
        string name
        string description
        string frequency
        string effectiveness
        date last_tested
    }

    RISK {
        string risk_id PK
        string name
        string rating
        string category
    }

    PROCESS {
        string process_id PK
        string name
        string owner
        string parent_process FK
    }

    REGULATION {
        string reg_id PK
        string name
        string jurisdiction
        string version
    }

    FINDING {
        string finding_id PK
        string description
        string severity
        date identified_date
        string status
    }

    CONTROL ||--o{ RISK : "MITIGATES"
    CONTROL ||--o{ PROCESS : "GOVERNS"
    CONTROL ||--o{ REGULATION : "MAPS_TO"
    PROCESS ||--o{ PROCESS : "PARENT_OF"
    FINDING ||--o{ CONTROL : "FOUND_IN"
```

### Example: Document Domain Graph

```mermaid
erDiagram
    DOCUMENT {
        string doc_id PK
        string title
        string doc_type
        string status
        date effective_date
        string owner
        string previous_version FK
    }

    SECTION {
        string section_id PK
        string doc_id FK
        string heading
        int order_index
        text content_summary
    }

    TAG {
        string tag_id PK
        string name
        string category
    }

    COLLECTION {
        string collection_id PK
        string name
        string domain_scope
    }

    DOCUMENT ||--o{ SECTION : "HAS_SECTION"
    DOCUMENT ||--o{ TAG : "TAGGED_WITH"
    COLLECTION ||--o{ DOCUMENT : "CONTAINS"
    DOCUMENT ||--o{ DOCUMENT : "SUPERSEDES"
    DOCUMENT ||--o{ DOCUMENT : "REFERENCES"
```

---

## 3. API Request / Response Models

```mermaid
erDiagram
    SEARCH_REQUEST {
        string query
        string domain
        int top_k
        string search_mode
        json screen_context
    }

    PARSED_INTENT {
        string query_type
        json entities
        json expanded_terms
        string cypher_hint
        string structural_filter
        string target_domain
        json domain_context
        float confidence
    }

    SEARCH_RESPONSE {
        string query
        string domain
        json results
        string synthesis
        float latency_ms
        int result_count
        json intent
    }

    SEARCH_RESULT_ITEM {
        string chunk_id
        string domain
        string element_id
        string element_type
        string name
        string description
        string breadcrumb
        json lineage_path
        float score
        int rank
        json sources
        string source_url
    }

    INDEX_REQUEST {
        string domain_id
        string mode
        string file_path
        string raw_xml
        bool background
    }

    INDEX_RESPONSE {
        string domain_id
        string status
        int entities_processed
        int graph_nodes
        int vector_docs
        int lucene_docs
        float duration_ms
        json errors
        string job_id
    }

    SEARCH_REQUEST ||--|| PARSED_INTENT : "produces"
    SEARCH_RESPONSE ||--o{ SEARCH_RESULT_ITEM : "contains"
    INDEX_REQUEST ||--|| INDEX_RESPONSE : "produces"
```

---

## 4. Domain Config Composition Model

Shows how all config parts compose into a registered domain.

```mermaid
erDiagram
    DOMAIN_CONFIG {
        string domain_id PK
        string display_name
    }

    SOURCE_CONNECTOR {
        string connector_type
        json connection_params
        bool supports_incremental
        bool supports_realtime
    }

    ENTITY_TYPE_REGISTRY {
        string domain_id FK
        int type_count
    }

    GRAPH_SCHEMA {
        string domain_namespace
        int node_label_count
        int relationship_count
        json boost_edges
    }

    BREADCRUMB_TEMPLATE {
        string template_type
        int max_total_length
        int lineage_depth
        string separator
    }

    INTENT_PROMPT_CONFIG {
        int synonym_map_size
        int cypher_pattern_count
        string grounding_format
    }

    TRIGGER_CONFIG {
        string mode
        string schedule_cron
        string event_source
        bool full_reindex_on_startup
    }

    DOMAIN_CONFIG ||--|| SOURCE_CONNECTOR : "uses"
    DOMAIN_CONFIG ||--|| ENTITY_TYPE_REGISTRY : "has"
    DOMAIN_CONFIG ||--|| GRAPH_SCHEMA : "has"
    DOMAIN_CONFIG ||--|| BREADCRUMB_TEMPLATE : "has"
    DOMAIN_CONFIG ||--|| INTENT_PROMPT_CONFIG : "has"
    DOMAIN_CONFIG ||--|| TRIGGER_CONFIG : "has"
```
