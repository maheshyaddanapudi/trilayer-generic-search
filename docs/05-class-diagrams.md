# 05 — Class Diagrams

---

## 1. Domain Plugin Layer

```mermaid
classDiagram
    class DomainConfig {
        +str domain_id
        +str display_name
        +str description
        +SourceConnector connector
        +EntityTypeRegistry entity_types
        +GraphSchema graph_schema
        +BreadcrumbTemplate breadcrumb_template
        +IntentPromptConfig intent_prompt
        +TriggerConfig trigger_config
        +int rrf_k
        +float graph_boost_factor
        +int graph_boost_top_n
        +int default_top_k
        +bool namespace_isolated
    }

    class DomainRegistry {
        -dict _domains
        -DomainRegistry _instance
        +register(DomainConfig) void
        +unregister(str) void
        +get(str) DomainConfig
        +list_domains() list
        +is_registered(str) bool
        +all_configs() list
        +get_instance()$ DomainRegistry
    }

    class SourceConnector {
        <<abstract>>
        +connect() void
        +disconnect() void
        +fetch_all() Iterator
        +fetch_since(datetime) Iterator
        +subscribe(Callable) Subscription
        +supports_incremental bool
        +supports_realtime bool
    }

    class EntityTypeRegistry {
        -dict _types
        +register(EntityTypeDefinition) void
        +get(str) EntityTypeDefinition
        +all_types() list
        +type_names() list
    }

    class EntityTypeDefinition {
        +str name
        +str id_field
        +str display_field
        +str description_field
        +list properties
        +str parent_type
        +list searchable_fields
    }

    class GraphSchema {
        +str domain_namespace
        +dict node_labels
        +list relationships
        +list traversal_rules
        +list boost_edges
    }

    class RelationshipDefinition {
        +str type_name
        +str from_label
        +str to_label
        +list properties
        +bool directed
        +str inverse_name
    }

    class TraversalRule {
        +str relationship_type
        +TraversalDirection direction
        +int max_depth
        +bool use_for_boost
    }

    class BreadcrumbTemplate {
        <<abstract>>
        +int max_total_length
        +generate(RawEntity, BreadcrumbContext) str
    }

    class TemplateBreadcrumbTemplate {
        -BreadcrumbSlot identity_slot
        -BreadcrumbSlot description_slot
        -list attribute_slots
        -int lineage_depth
        -str separator
        +generate(RawEntity, BreadcrumbContext) str
    }

    class IntentPromptConfig {
        +dict entity_type_descriptions
        +dict synonym_expansion_map
        +dict query_type_examples
        +dict cypher_hint_patterns
        +str grounding_format_description
        +str extra_context
    }

    class TriggerConfig {
        +TriggerMode mode
        +str schedule_cron
        +str event_source
        +bool full_reindex_on_startup
    }

    DomainRegistry "1" --> "N" DomainConfig : holds
    DomainConfig --> SourceConnector
    DomainConfig --> EntityTypeRegistry
    DomainConfig --> GraphSchema
    DomainConfig --> BreadcrumbTemplate
    DomainConfig --> IntentPromptConfig
    DomainConfig --> TriggerConfig
    EntityTypeRegistry "1" --> "N" EntityTypeDefinition : registers
    GraphSchema "1" --> "N" RelationshipDefinition : defines
    GraphSchema "1" --> "N" TraversalRule : defines
    BreadcrumbTemplate <|-- TemplateBreadcrumbTemplate
```

---

## 2. Source Connector Hierarchy

```mermaid
classDiagram
    class SourceConnector {
        <<abstract>>
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +subscribe(Callable) Subscription
        +supports_incremental bool
        +supports_realtime bool
    }

    class XMLFileConnector {
        -Path file_path
        -EntityTypeRegistry entity_types
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +supports_incremental bool
    }

    class DatabaseConnector {
        -str connection_string
        -dict table_mappings
        -Engine _engine
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +supports_incremental bool
    }

    class RESTAPIConnector {
        -str base_url
        -dict auth_config
        -dict endpoint_mappings
        -httpx.AsyncClient _client
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +supports_incremental bool
    }

    class FileSystemConnector {
        -Path watch_dir
        -list supported_mimes
        -TextExtractor _extractor
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +process_upload(bytes, str, str) Iterator~RawEntity~
        +supports_incremental bool
    }

    class EventStreamConnector {
        -str broker_url
        -str topic
        -KafkaConsumer _consumer
        +connect() void
        +disconnect() void
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +subscribe(Callable) Subscription
        +supports_realtime bool
    }

    class ScreenContextConnector {
        +fetch_all() Iterator~RawEntity~
        +fetch_since(datetime) Iterator~RawEntity~
        +from_request_context(dict) Iterator~RawEntity~
    }

    SourceConnector <|-- XMLFileConnector
    SourceConnector <|-- DatabaseConnector
    SourceConnector <|-- RESTAPIConnector
    SourceConnector <|-- FileSystemConnector
    SourceConnector <|-- EventStreamConnector
    SourceConnector <|-- ScreenContextConnector
```

---

## 3. Index Layer

```mermaid
classDiagram
    class IndexWriter {
        <<abstract>>
        +index(list~MetadataChunk~) int
        +delete(list~str~) int
        +clear(str) void
        +is_ready bool
    }

    class VectorIndexWriter {
        -SentenceTransformer _model
        -faiss.Index _index
        -dict _chunks
        -threading.Lock _lock
        -str _model_name
        -int _dimension
        +index(list~MetadataChunk~) int
        +delete(list~str~) int
        +clear(str) void
        +similarity_search(list, int, str) list
        +is_ready bool
    }

    class LuceneIndexWriter {
        -Path _index_dir
        -dict _indices
        +index(list~MetadataChunk~) int
        +delete(list~str~) int
        +clear(str) void
        +keyword_search(str, int, str) list
        +is_ready bool
    }

    class GraphIndexWriter {
        -neo4j.Driver _driver
        -str _uri
        +index(list~MetadataChunk~) int
        +index_relationships(list, GraphSchema) int
        +delete(list~str~) int
        +clear(str) void
        +cypher_query(str, dict) list
        +get_neighbours(list, list, int) list~MetadataChunk~
        +get_ancestors(str, str) list~RawEntity~
        +close() void
        +is_ready bool
    }

    class IndexReader {
        <<abstract>>
        +search(ParsedIntent, int) list~SearchResult~
        +is_ready bool
    }

    class VectorSearch {
        -VectorIndexWriter _writer
        -SentenceTransformer _embedder
        +search(ParsedIntent, int) list~SearchResult~
        -_build_query_text(ParsedIntent) str
        +is_ready bool
    }

    class LuceneSearch {
        -LuceneIndexWriter _writer
        +search(ParsedIntent, int) list~SearchResult~
        -_build_query(ParsedIntent) Query
        +is_ready bool
    }

    class GraphSearch {
        -GraphIndexWriter _writer
        +search(ParsedIntent, int) list~SearchResult~
        -_entity_lookup(list, int) list
        -_cypher_traversal(str, int) list
        +is_ready bool
    }

    IndexWriter <|-- VectorIndexWriter
    IndexWriter <|-- LuceneIndexWriter
    IndexWriter <|-- GraphIndexWriter
    IndexReader <|-- VectorSearch
    IndexReader <|-- LuceneSearch
    IndexReader <|-- GraphSearch
    VectorSearch --> VectorIndexWriter
    LuceneSearch --> LuceneIndexWriter
    GraphSearch --> GraphIndexWriter
```

---

## 4. Aggregation Pipeline

```mermaid
classDiagram
    class ResultPostProcessor {
        <<abstract>>
        +process(dict, int, DomainConfig) list~SearchResult~
    }

    class RRFAggregator {
        +process(dict, int, DomainConfig) list~SearchResult~
        -_rrf_score(dict, int) dict
    }

    class GraphBoostingAggregator {
        -GraphIndexWriter _graph_writer
        +process(dict, int, DomainConfig) list~SearchResult~
        -_get_boost_candidates(list, DomainConfig) list
        -_apply_boost(list, list, float) list
    }

    class AggregationPipeline {
        -list~ResultPostProcessor~ _stages
        +run(dict, int, DomainConfig) list~SearchResult~
        +add_stage(ResultPostProcessor) void
    }

    ResultPostProcessor <|-- RRFAggregator
    ResultPostProcessor <|-- GraphBoostingAggregator
    AggregationPipeline "1" --> "N" ResultPostProcessor : runs in order
```

---

## 5. LLM Layer

```mermaid
classDiagram
    class LLMClient {
        <<abstract>>
        +complete(str, str) str
        +complete_with_retry(str, str, int) str
    }

    class AnthropicLLMClient {
        -Anthropic _client
        -str _model
        +complete(str, str) str
    }

    class IntentParser {
        -LLMClient _client
        -DomainRegistry _registry
        +parse(str, str, dict) ParsedIntent
        -_build_system_prompt(DomainConfig) str
        -_parse_llm_response(str, str) ParsedIntent
        -_heuristic_fallback(str) ParsedIntent
    }

    class Synthesizer {
        -LLMClient _client
        +synthesize(str, list~MetadataChunk~, DomainConfig) str
        -_build_breadcrumb_context(list) str
        -_build_system_prompt(DomainConfig) str
    }

    LLMClient <|-- AnthropicLLMClient
    IntentParser --> LLMClient
    Synthesizer --> LLMClient
```

---

## 6. Ingestion Pipeline

```mermaid
classDiagram
    class IngestionOrchestrator {
        -DomainRegistry _registry
        -VectorIndexWriter _vector
        -LuceneIndexWriter _lucene
        -GraphIndexWriter _graph
        -BreadcrumbGenerator _breadcrumb_gen
        +ingest_domain(str, IngestionMode) IngestionResult
        +handle_change_event(ChangeEvent) void
        +ingest_all_domains() list~IngestionResult~
        -_ingest_batch(list, DomainConfig) void
    }

    class BreadcrumbGenerator {
        -DomainRegistry _registry
        -GraphIndexWriter _graph
        +generate(RawEntity, str) MetadataChunk
        -_build_context(RawEntity, str) BreadcrumbContext
    }

    class ChangeDetector {
        +classify(ChangeEvent) ChangeEventType
        +propagate_to_neighbours(str, str, GraphIndexWriter) list~str~
    }

    class IngestionResult {
        +str domain_id
        +IngestionMode mode
        +int entities_processed
        +int graph_nodes
        +int vector_docs
        +int lucene_docs
        +float duration_ms
        +list errors
        +datetime checkpoint
    }

    IngestionOrchestrator --> BreadcrumbGenerator
    IngestionOrchestrator --> ChangeDetector
    IngestionOrchestrator --> DomainRegistry
    IngestionOrchestrator --> IngestionResult
```

---

## 7. Search Orchestrator (LangGraph)

```mermaid
classDiagram
    class SearchOrchestrator {
        -StateGraph _graph
        -VectorSearch _vector
        -LuceneSearch _lucene
        -GraphSearch _graph_search
        -IntentParser _intent_parser
        -Synthesizer _synthesizer
        -AggregationPipeline _aggregator
        -DomainRegistry _registry
        +run(str, str, dict) SearchState
        -_build_graph() StateGraph
        -_parse_intent_node(SearchState) SearchState
        -_tri_search_node(SearchState) SearchState
        -_aggregate_node(SearchState) SearchState
        -_synthesize_node(SearchState) SearchState
    }

    class SearchState {
        +str query
        +str domain
        +dict screen_context
        +ParsedIntent intent
        +list vector_results
        +list lucene_results
        +list graph_results
        +list merged_results
        +str synthesis
        +float latency_ms
        +str error
    }

    SearchOrchestrator --> SearchState
    SearchOrchestrator --> VectorSearch
    SearchOrchestrator --> LuceneSearch
    SearchOrchestrator --> GraphSearch
    SearchOrchestrator --> IntentParser
    SearchOrchestrator --> Synthesizer
    SearchOrchestrator --> AggregationPipeline
```

---

## 8. Core Data Models

```mermaid
classDiagram
    class RawEntity {
        +str entity_id
        +str entity_type
        +str name
        +str description
        +dict properties
        +str parent_id
        +str parent_type
        +list relationships
        +str source_domain
        +str source_url
        +datetime last_modified
    }

    class RawRelationship {
        +str source_id
        +str target_id
        +str relationship_type
        +dict properties
    }

    class MetadataChunk {
        +str chunk_id
        +str domain
        +str element_id
        +str element_type
        +str name
        +str description
        +str breadcrumb
        +list lineage_path
        +dict attributes
        +str source_url
        +list embedding
    }

    class SearchResult {
        +MetadataChunk chunk
        +float score
        +int rank
        +list sources
        +float rrf_score
        +bool boost_applied
    }

    class ParsedIntent {
        +QueryType query_type
        +list entities
        +list expanded_terms
        +str cypher_hint
        +str structural_filter
        +str target_domain
        +dict domain_context
        +float confidence
    }

    class ChangeEvent {
        +str event_id
        +ChangeEventType event_type
        +str domain
        +str entity_id
        +str entity_type
        +dict payload
        +datetime timestamp
    }

    RawEntity "1" --> "N" RawRelationship : has
    SearchResult --> MetadataChunk : wraps
```

---

## 9. Session Layer

```mermaid
classDiagram
    class SessionChunk {
        +str chunk_id
        +str session_id
        +SessionSourceType source_type
        +str domain
        +str name
        +str description
        +str breadcrumb
        +dict attributes
        +list linked_permanent_ids
        +datetime created_at
        +int ttl_seconds
        +is_expired() bool
        +to_metadata_chunk() MetadataChunk
    }

    class SessionRegistry {
        -dict _sessions
        -asyncio.Lock _lock
        -int _max_chunks_per_session
        +create_session() str
        +end_session(str) void
        +add_chunk(str, SessionChunk) void
        +get_chunks(str) list
        +materialise_screen_context(str, dict, str, GraphIndexWriter) list
        +inject_api_response(str, dict, str, str, list) SessionChunk
        +purge_expired() int
        +session_exists(str) bool
        +chunk_count(str) int
    }

    class SessionSearch {
        -SessionRegistry _registry
        -SentenceTransformer _embedder
        +search(ParsedIntent, int, str) list~SearchResult~
        -_cosine_similarity(list, list) list
    }

    class SessionLinkBoostingAggregator {
        -SessionRegistry _registry
        +process(dict, int, DomainConfig) list~SearchResult~
        -_collect_linked_ids(list) set
        -_apply_session_boost(list, set, float) list
    }

    class SessionSourceType {
        <<enumeration>>
        SCREEN_CONTEXT
        API_RESPONSE
        DYNAMIC_RESULT
        USER_ANNOTATION
    }

    SessionRegistry "1" --> "N" SessionChunk : holds
    SessionSearch --> SessionRegistry : queries
    SessionLinkBoostingAggregator --> SessionRegistry : reads linked_ids
    SessionChunk --> SessionSourceType : typed by
    SessionChunk ..> MetadataChunk : adapts to
    ResultPostProcessor <|-- SessionLinkBoostingAggregator
    IndexReader <|-- SessionSearch
```
