# 03 — Low-Level Design

---

## 1. Canonical Data Models

These types are the shared language between all layers. Domain plugins produce them;
the engine core consumes them. No domain-specific types cross the plugin boundary.

### 1.1 RawEntity

The output of a `SourceConnector`. Represents a single entity before breadcrumb
generation.

```python
@dataclass
class PropertyDefinition:
    name: str
    field_type: FieldType          # STRING | NUMBER | BOOLEAN | DATE | LIST
    required: bool = False
    searchable: bool = True

@dataclass
class RawRelationship:
    source_id: str
    target_id: str
    relationship_type: str          # matches GraphSchema.relationships[*].type_name
    properties: dict[str, Any] = field(default_factory=dict)

@dataclass
class RawEntity:
    entity_id: str                  # unique within domain
    entity_type: str                # matches EntityTypeRegistry key
    name: str
    description: str
    properties: dict[str, Any]      # arbitrary key-value pairs
    parent_id: str | None = None
    parent_type: str | None = None
    relationships: list[RawRelationship] = field(default_factory=list)
    source_domain: str = ""         # populated by IngestionOrchestrator
    source_url: str | None = None   # back-link to origin system
    last_modified: datetime | None = None
```

### 1.2 MetadataChunk

The indexable unit. One `RawEntity` produces exactly one `MetadataChunk`.

```python
@dataclass
class MetadataChunk:
    chunk_id: str                   # f"{domain}::{entity_type}::{entity_id}"
    domain: str
    element_id: str
    element_type: str
    name: str
    description: str
    breadcrumb: str                 # the formatted, searchable text
    lineage_path: list[str]         # ["grandparent", "parent", "self"]
    attributes: dict[str, Any]      # structured properties for filtering
    source_url: str | None = None
    embedding: list[float] | None = None   # populated by VectorIndexWriter
```

### 1.3 SearchResult

Returned by each index reader and merged by the aggregator.

```python
@dataclass
class SearchResult:
    chunk: MetadataChunk
    score: float                    # normalised [0, 1]
    rank: int                       # 1-based position within its index
    sources: list[str]              # e.g. ["vector", "lucene"] after merge
    rrf_score: float = 0.0          # populated by RRFAggregator
    boost_applied: bool = False
```

### 1.4 ParsedIntent

Output of `IntentParser`. Drives all three index searches.

```python
class QueryType(str, Enum):
    LOOKUP     = "lookup"
    DISCOVERY  = "discovery"
    TRAVERSAL  = "traversal"

@dataclass
class ParsedIntent:
    query_type: QueryType
    entities: list[str]             # extracted exact identifiers
    expanded_terms: list[str]       # semantic synonyms
    cypher_hint: str | None         # Cypher fragment for traversal queries
    structural_filter: str | None   # graph scope description
    target_domain: str | None       # None means search all domains
    domain_context: dict | None     # from screen_context injection
    confidence: float = 1.0         # 0–1; drops to 0 if heuristic fallback used
```

### 1.5 SearchState (LangGraph)

Typed state object threaded through the LangGraph pipeline.

```python
class SearchState(TypedDict):
    query: str
    domain: str | None
    screen_context: dict | None
    session_id: str | None              # NEW — routes to SessionRegistry
    intent: ParsedIntent | None
    vector_results: list[SearchResult]
    lucene_results: list[SearchResult]
    graph_results: list[SearchResult]
    session_results: list[SearchResult] # NEW — from SessionSearch
    merged_results: list[SearchResult]
    synthesis: str
    latency_ms: float
    error: str | None
```

### 1.6 SessionChunk

An ephemeral unit held in the Session Layer. Never written to any persistent store.

```python
class SessionSourceType(str, Enum):
    SCREEN_CONTEXT   = "screen_context"    # entities visible in the UI
    API_RESPONSE     = "api_response"      # live data fetched during a query
    DYNAMIC_RESULT   = "dynamic_result"    # result injected from a prior query
    USER_ANNOTATION  = "user_annotation"   # explicit user-provided context

@dataclass
class SessionChunk:
    chunk_id: str                           # f"session::{session_id}::{source_type}::{item_id}"
    session_id: str
    source_type: SessionSourceType
    domain: str                             # which domain the linked permanent data belongs to
    name: str
    description: str
    breadcrumb: str
    attributes: dict[str, Any]
    linked_permanent_ids: list[str]         # chunk_ids in permanent indices this chunk is derived from
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 1800                 # 30 min default; 0 = never expires

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds == 0:
            return False
        return (datetime.utcnow() - self.created_at).total_seconds() > self.ttl_seconds

    def to_metadata_chunk(self) -> "MetadataChunk":
        """Adapts to MetadataChunk so SearchResult can wrap it uniformly."""
        return MetadataChunk(
            chunk_id=self.chunk_id,
            domain=self.domain,
            element_id=self.chunk_id,
            element_type=f"session:{self.source_type.value}",
            name=self.name,
            description=self.description,
            breadcrumb=f"[LIVE] {self.breadcrumb}",
            lineage_path=["session", self.source_type.value, self.name],
            attributes={**self.attributes, "_session_id": self.session_id},
        )
```

### 1.7 ChangeEvent

Emitted by source systems for incremental updates.

```python
class ChangeEventType(str, Enum):
    ADD    = "add"
    UPDATE = "update"
    DELETE = "delete"

@dataclass
class ChangeEvent:
    event_id: str
    event_type: ChangeEventType
    domain: str
    entity_id: str
    entity_type: str
    payload: dict[str, Any]         # full entity for ADD/UPDATE; empty for DELETE
    timestamp: datetime
```

---

## 2. Domain Plugin Interfaces

### 2.1 SourceConnector

```python
class SourceConnector(ABC):
    """
    Abstraction over any data source.
    Implementations: XMLFileConnector, DatabaseConnector,
    RESTAPIConnector, FileSystemConnector, EventStreamConnector.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection. Called once before any fetch."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release connection resources."""

    @abstractmethod
    def fetch_all(self) -> Iterator[RawEntity]:
        """
        Full snapshot: yield every entity in the source.
        Used for initial indexing and full re-index.
        """

    @abstractmethod
    def fetch_since(self, checkpoint: datetime) -> Iterator[RawEntity]:
        """
        Incremental: yield only entities modified after checkpoint.
        Used for scheduled incremental index runs.
        Returns empty iterator if source does not support incremental.
        """

    def subscribe(self, callback: Callable[[ChangeEvent], None]) -> "Subscription":
        """
        Optional: register a callback for real-time change events.
        Only implemented by event-stream connectors (Kafka, webhooks).
        Default: raises NotImplementedError (not required for batch sources).
        """
        raise NotImplementedError

    @property
    def supports_incremental(self) -> bool:
        """Override to True if fetch_since is implemented."""
        return False

    @property
    def supports_realtime(self) -> bool:
        """Override to True if subscribe is implemented."""
        return False
```

### 2.2 EntityTypeRegistry

```python
@dataclass
class EntityTypeDefinition:
    name: str                           # e.g. "Account", "Employee"
    id_field: str                       # which property is the unique ID
    display_field: str                  # shown in result titles
    description_field: str              # feeds into breadcrumb description slot
    properties: list[PropertyDefinition]
    parent_type: str | None = None      # enables hierarchy traversal
    searchable_fields: list[str] = field(default_factory=list)
    icon: str | None = None             # optional UI hint

class EntityTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, EntityTypeDefinition] = {}

    def register(self, definition: EntityTypeDefinition) -> None:
        self._types[definition.name] = definition

    def get(self, type_name: str) -> EntityTypeDefinition:
        if type_name not in self._types:
            raise KeyError(f"Entity type '{type_name}' not registered")
        return self._types[type_name]

    def all_types(self) -> list[EntityTypeDefinition]:
        return list(self._types.values())

    def type_names(self) -> list[str]:
        return list(self._types.keys())
```

### 2.3 GraphSchema

```python
class TraversalDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND  = "inbound"
    BOTH     = "both"

@dataclass
class NodeLabel:
    label: str                          # Neo4j node label
    entity_type: str                    # maps to EntityTypeRegistry key
    key_property: str                   # unique constraint property
    index_properties: list[str]         # additional Neo4j text indices

@dataclass
class RelationshipDefinition:
    type_name: str                      # e.g. "PARENT_OF", "REPORTS_TO"
    from_label: str                     # source node label
    to_label: str                       # target node label
    properties: list[PropertyDefinition] = field(default_factory=list)
    directed: bool = True
    inverse_name: str | None = None     # e.g. "CHILD_OF" for "PARENT_OF"

@dataclass
class TraversalRule:
    relationship_type: str
    direction: TraversalDirection
    max_depth: int = 3
    use_for_boost: bool = True          # include in GraphBoostingAggregator

@dataclass
class GraphSchema:
    domain_namespace: str               # prefix for Neo4j labels: f"{namespace}_{label}"
    node_labels: dict[str, NodeLabel]   # entity_type → NodeLabel
    relationships: list[RelationshipDefinition]
    traversal_rules: list[TraversalRule]
    boost_edges: list[str]              # relationship types used in graph boosting
```

### 2.4 BreadcrumbTemplate

```python
@dataclass
class BreadcrumbSlot:
    field_path: str             # dot-separated path into RawEntity properties
    label: str | None = None    # optional prefix: "parent:" or "owner="
    max_length: int | None = None

class BreadcrumbTemplate(ABC):
    max_total_length: int = 512

    @abstractmethod
    def generate(
        self,
        entity: RawEntity,
        context: "BreadcrumbContext",
    ) -> str:
        """
        Produce the breadcrumb string for this entity.
        context provides parent entity data for lineage slots.
        """

@dataclass
class BreadcrumbContext:
    ancestors: list[RawEntity]          # ordered from root to immediate parent
    domain_name: str

class TemplateBreadcrumbTemplate(BreadcrumbTemplate):
    """
    Configurable breadcrumb using slot definitions.
    Default template: [identity] | [type] | [lineage] | [description] | [attributes]
    """
    def __init__(
        self,
        identity_slot: BreadcrumbSlot,
        description_slot: BreadcrumbSlot,
        attribute_slots: list[BreadcrumbSlot],
        lineage_depth: int = 2,
        separator: str = " | ",
    ) -> None: ...

    def generate(self, entity: RawEntity, context: BreadcrumbContext) -> str: ...
```

### 2.5 IntentPromptConfig

```python
@dataclass
class IntentPromptConfig:
    entity_type_descriptions: dict[str, str]
    # e.g. {"Account": "financial accounts like REVENUE, COGS, SAAS_REVENUE"}

    synonym_expansion_map: dict[str, list[str]]
    # e.g. {"revenue": ["arr", "mrr", "income", "REVENUE"]}

    query_type_examples: dict[str, list[str]]
    # e.g. {"traversal": ["children of REVENUE", "what rolls up to OPEX"]}

    cypher_hint_patterns: dict[str, str]
    # e.g. {"hierarchy": "MATCH (a:Account)-[:PARENT_OF*]->(c) WHERE a.code=$code"}

    grounding_format_description: str
    # e.g. "Sheet > Version > Account hierarchy path"

    extra_context: str = ""
    # Domain-specific instructions appended to the base system prompt
```

### 2.6 DomainConfig (the plugin bundle)

```python
class TriggerMode(str, Enum):
    MANUAL       = "manual"
    SCHEDULED    = "scheduled"
    EVENT_DRIVEN = "event_driven"
    REALTIME     = "realtime"

@dataclass
class TriggerConfig:
    mode: TriggerMode = TriggerMode.MANUAL
    schedule_cron: str | None = None        # e.g. "0 */4 * * *" (every 4h)
    event_source: str | None = None         # Kafka topic, webhook URL
    full_reindex_on_startup: bool = True

@dataclass
class DomainConfig:
    domain_id: str                          # slug: "financial_metadata", "hr", "docs"
    display_name: str
    description: str
    connector: SourceConnector
    entity_types: EntityTypeRegistry
    graph_schema: GraphSchema
    breadcrumb_template: BreadcrumbTemplate
    intent_prompt: IntentPromptConfig
    trigger_config: TriggerConfig
    rrf_k: int = 60                         # RRF constant for this domain
    graph_boost_factor: float = 1.5
    graph_boost_top_n: int = 3
    default_top_k: int = 10
    namespace_isolated: bool = True         # separate graph/vector namespaces
```

---

## 3. Engine Core Interfaces

### 3.1 Index Writers

```python
class IndexWriter(ABC):
    @abstractmethod
    def index(self, chunks: list[MetadataChunk]) -> int:
        """Index a batch of chunks. Returns count of successfully indexed items."""

    @abstractmethod
    def delete(self, chunk_ids: list[str]) -> int:
        """Remove chunks by ID. Returns count deleted."""

    @abstractmethod
    def clear(self, domain: str | None = None) -> None:
        """Clear all entries (optionally scoped to a domain)."""

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """True if the underlying store is initialised and reachable."""
```

```python
class VectorIndexWriter(IndexWriter):
    """FAISS-backed. Thread-safe via internal lock."""
    def __init__(self, model_name: str, dimension: int = 384) -> None: ...
    def index(self, chunks: list[MetadataChunk]) -> int: ...
    def similarity_search(
        self, query_vector: list[float], top_k: int, domain: str | None = None
    ) -> list[tuple[MetadataChunk, float]]: ...

class LuceneIndexWriter(IndexWriter):
    """Whoosh-backed. One index per domain in index_dir/domain_id/."""
    def __init__(self, index_dir: Path) -> None: ...
    def index(self, chunks: list[MetadataChunk]) -> int: ...
    def keyword_search(
        self, query_str: str, top_k: int, domain: str | None = None
    ) -> list[tuple[MetadataChunk, float]]: ...

class GraphIndexWriter(IndexWriter):
    """Neo4j-backed. Uses MERGE for idempotent upserts."""
    def __init__(self, uri: str, user: str, password: str) -> None: ...
    def index(self, chunks: list[MetadataChunk]) -> int: ...
    def index_relationships(self, relationships: list[RawRelationship], schema: GraphSchema) -> int: ...
    def cypher_query(self, cypher: str, params: dict) -> list[dict]: ...
    def get_neighbours(
        self, entity_ids: list[str], edge_types: list[str], depth: int = 1
    ) -> list[MetadataChunk]: ...
    def close(self) -> None: ...
```

### 3.2 Index Readers (Search Engines)

```python
class IndexReader(ABC):
    @abstractmethod
    def search(self, intent: ParsedIntent, top_k: int) -> list[SearchResult]: ...

    @property
    @abstractmethod
    def is_ready(self) -> bool: ...

class VectorSearch(IndexReader):
    def __init__(self, writer: VectorIndexWriter, embedder: SentenceTransformer) -> None: ...
    def search(self, intent: ParsedIntent, top_k: int) -> list[SearchResult]: ...

class LuceneSearch(IndexReader):
    def __init__(self, writer: LuceneIndexWriter) -> None: ...
    def search(self, intent: ParsedIntent, top_k: int) -> list[SearchResult]: ...

class GraphSearch(IndexReader):
    def __init__(self, writer: GraphIndexWriter) -> None: ...
    def search(self, intent: ParsedIntent, top_k: int) -> list[SearchResult]: ...
```

### 3.3 Session Layer

```python
class SessionRegistry:
    """
    In-process store for SessionChunks, keyed by session_id.
    Thread-safe via asyncio.Lock.
    Auto-purge runs on every access and on a background schedule.
    """
    def __init__(self, max_chunks_per_session: int = 200) -> None: ...

    async def create_session(self) -> str:
        """Generate and register a new session_id. Returns the ID."""

    async def end_session(self, session_id: str) -> None:
        """Immediately remove all chunks for this session."""

    async def add_chunk(self, session_id: str, chunk: SessionChunk) -> None:
        """Add a chunk; evicts oldest if max_chunks_per_session reached."""

    async def get_chunks(self, session_id: str) -> list[SessionChunk]:
        """Return all non-expired chunks for this session."""

    async def materialise_screen_context(
        self,
        session_id: str,
        screen_context: dict,
        domain: str,
        graph_writer: GraphIndexWriter,
    ) -> list[SessionChunk]:
        """
        Convert screen_context payload into SessionChunks.
        Looks up permanent chunk_ids for each visible entity via GraphIndexWriter.
        Returns the newly created SessionChunks.
        """

    async def inject_api_response(
        self,
        session_id: str,
        response_data: dict,
        domain: str,
        source_description: str,
        linked_permanent_ids: list[str],
    ) -> SessionChunk:
        """Wrap a live API response as a SessionChunk and add it to the session."""

    async def purge_expired(self) -> int:
        """Remove all expired chunks across all sessions. Returns count purged."""

    def session_exists(self, session_id: str) -> bool: ...
    def chunk_count(self, session_id: str) -> int: ...


class SessionSearch:
    """
    Searches in-memory SessionChunks for a given session.
    Uses cosine similarity against the same embedding model as VectorSearch.
    O(N) linear scan — acceptable because N (chunks per session) is small.
    """
    def __init__(
        self,
        registry: SessionRegistry,
        embedder: SentenceTransformer,
    ) -> None: ...

    async def search(
        self,
        intent: ParsedIntent,
        top_k: int,
        session_id: str | None,
    ) -> list[SearchResult]:
        """
        Returns [] immediately if session_id is None or session has no chunks.
        Session results are marked sources=["session"] and carry boost_applied=False.
        """
```

### 3.4 Aggregation Chain

```python
class ResultPostProcessor(ABC):
    """One stage in the aggregation pipeline."""
    @abstractmethod
    def process(
        self,
        results: dict[str, list[SearchResult]],   # keyed by index name
        top_k: int,
        config: DomainConfig,
    ) -> list[SearchResult]: ...

class RRFAggregator(ResultPostProcessor):
    def process(self, results, top_k, config) -> list[SearchResult]: ...

class GraphBoostingAggregator(ResultPostProcessor):
    """Must follow RRFAggregator in the chain."""
    def __init__(self, graph_writer: GraphIndexWriter) -> None: ...
    def process(self, results, top_k, config) -> list[SearchResult]: ...

class SessionLinkBoostingAggregator(ResultPostProcessor):
    """
    Must follow GraphBoostingAggregator in the chain.
    For each session result with linked_permanent_ids:
      - Boost those permanent chunks in merged_results by session_link_boost_factor
      - Session chunks appear in results labelled element_type='session:*'
    """
    def __init__(self, registry: SessionRegistry) -> None: ...
    def process(self, results, top_k, config) -> list[SearchResult]: ...

class AggregationPipeline:
    """Ordered chain executor."""
    def __init__(self, stages: list[ResultPostProcessor]) -> None: ...
    def run(
        self,
        results: dict[str, list[SearchResult]],
        top_k: int,
        config: DomainConfig,
    ) -> list[SearchResult]: ...
```

### 3.4 LLM Layer

```python
class LLMClient(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: str) -> str: ...

    async def complete_with_retry(
        self, prompt: str, system: str, max_retries: int = 3
    ) -> str:
        """Default retry logic with exponential backoff."""

class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None: ...
    async def complete(self, prompt: str, system: str) -> str: ...

class IntentParser:
    def __init__(self, client: LLMClient, domain_registry: "DomainRegistry") -> None: ...

    async def parse(
        self,
        query: str,
        domain: str | None = None,
        screen_context: dict | None = None,
    ) -> ParsedIntent: ...

    def _build_system_prompt(self, domain_config: DomainConfig | None) -> str: ...
    def _heuristic_fallback(self, query: str) -> ParsedIntent: ...

class Synthesizer:
    def __init__(self, client: LLMClient) -> None: ...

    async def synthesize(
        self,
        query: str,
        chunks: list[MetadataChunk],
        domain_config: DomainConfig | None,
    ) -> str: ...
```

### 3.5 Domain Registry

```python
class DomainRegistry:
    """
    Singleton registry. All registered domains are available to
    the ingestion orchestrator and search orchestrator.
    """
    _instance: "DomainRegistry | None" = None

    @classmethod
    def get_instance(cls) -> "DomainRegistry": ...

    def register(self, config: DomainConfig) -> None: ...
    def unregister(self, domain_id: str) -> None: ...
    def get(self, domain_id: str) -> DomainConfig: ...
    def list_domains(self) -> list[str]: ...
    def is_registered(self, domain_id: str) -> bool: ...
    def all_configs(self) -> list[DomainConfig]: ...
```

### 3.6 Ingestion Orchestrator

```python
class IngestionMode(str, Enum):
    FULL        = "full"
    INCREMENTAL = "incremental"

@dataclass
class IngestionResult:
    domain_id: str
    mode: IngestionMode
    entities_processed: int
    graph_nodes: int
    vector_docs: int
    lucene_docs: int
    duration_ms: float
    errors: list[str]
    checkpoint: datetime

class IngestionOrchestrator:
    def __init__(
        self,
        domain_registry: DomainRegistry,
        vector_writer: VectorIndexWriter,
        lucene_writer: LuceneIndexWriter,
        graph_writer: GraphIndexWriter,
        breadcrumb_generator: "BreadcrumbGenerator",
    ) -> None: ...

    async def ingest_domain(
        self, domain_id: str, mode: IngestionMode = IngestionMode.FULL
    ) -> IngestionResult: ...

    async def handle_change_event(self, event: ChangeEvent) -> None: ...

    async def ingest_all_domains(self) -> list[IngestionResult]: ...
```

### 3.7 SearchOrchestrator (LangGraph)

```python
class SearchOrchestrator:
    def __init__(
        self,
        vector_search: VectorSearch,
        lucene_search: LuceneSearch,
        graph_search: GraphSearch,
        session_search: SessionSearch,          # NEW
        intent_parser: IntentParser,
        synthesizer: Synthesizer,
        aggregation_pipeline: AggregationPipeline,
        domain_registry: DomainRegistry,
        session_registry: SessionRegistry,      # NEW
    ) -> None:
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """
        Nodes: parse_intent → quad_search → aggregate → synthesize
        All wired into a LangGraph StateGraph.
        """

    async def run(
        self,
        query: str,
        domain: str | None = None,
        screen_context: dict | None = None,
        session_id: str | None = None,          # NEW
    ) -> SearchState: ...
```

---

## 4. API Contract

### Endpoints

```
GET  /health                              System + index health
GET  /domains                             List registered domains
POST /domains/register                    Register a new domain (programmatic)
GET  /domains/{domain_id}                 Domain info + index stats
DELETE /domains/{domain_id}               Unregister

POST /domains/{domain_id}/index           Trigger full re-index
POST /domains/{domain_id}/index/incremental  Incremental index
GET  /domains/{domain_id}/index/status    Index health + last checkpoint

POST /search                              Multi-domain or targeted search
POST /search/{domain_id}                  Single-domain search (shorthand)

POST /sessions                            Create a new session → returns session_id
DELETE /sessions/{session_id}             End session and purge all chunks
POST /sessions/{session_id}/context       Inject context chunk (API response, annotation)
GET  /sessions/{session_id}/chunks        List session chunks (debug)

POST /debug/cypher                        Raw Cypher query (dev/debug)
POST /debug/vector                        Raw vector similarity (dev/debug)
```

### Search Request

```python
class SearchRequest(BaseModel):
    query: str
    domain: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    search_mode: Literal["hybrid", "vector", "lucene", "graph", "session"] = "hybrid"
    screen_context: dict | None = None
    session_id: str | None = None           # if provided, SessionSearch participates in dispatch
```

### Search Response

```python
class SearchResultItem(BaseModel):
    chunk_id: str
    domain: str
    element_id: str
    element_type: str
    name: str
    description: str
    breadcrumb: str
    lineage_path: list[str]
    score: float
    rank: int
    sources: list[str]
    source_url: str | None

class SearchResponse(BaseModel):
    query: str
    domain: str | None
    results: list[SearchResultItem]
    synthesis: str
    latency_ms: float
    result_count: int
    intent: dict                    # serialised ParsedIntent for transparency
```

---

## 5. Error Handling Strategy

| Failure | Behaviour |
|---|---|
| LLM call fails (intent) | Heuristic fallback activates; `intent.confidence = 0.0` |
| LLM call fails (synthesis) | Return top-K results without synthesis; flag in response |
| Neo4j unreachable | Graph search returns `[]`; vector + lucene continue; warning logged |
| Vector index empty | VectorSearch returns `[]`; other indices continue |
| Source connector fails | IngestionResult records error; partial results committed |
| Session ID not found | SessionSearch returns `[]`; permanent indices continue normally |
| Session TTL expired mid-query | Expired chunks silently skipped; no error returned |
| Session memory limit hit | Oldest chunks evicted (LRU); new chunk accepted |
| Unknown domain in request | 404 response with registered domain list |
| Malformed query | 422 with field-level validation from Pydantic |

The search pipeline **never hard-fails** at the aggregation or synthesis stage.
Partial results are always better than an error.

---

## 6. Configuration Schema

All runtime configuration via environment variables (consistent with POC):

```
# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# LLM
ANTHROPIC_API_KEY=...
LLM_MODEL=claude-sonnet-4-6

# Embedding
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384

# Index storage
FAISS_PERSIST_PATH=./data/faiss
WHOOSH_INDEX_DIR=./data/whoosh

# Ingestion
DEFAULT_BATCH_SIZE=100
MAX_BREADCRUMB_LENGTH=512
GRAPH_BOOST_FACTOR=1.5
RRF_K=60

# Session Layer
SESSION_TTL_SECONDS=1800
SESSION_MAX_CHUNKS=200
SESSION_MAX_TOTAL=10000
SESSION_PURGE_INTERVAL_SECONDS=300
SESSION_LINK_BOOST_FACTOR=1.3

# API
API_HOST=0.0.0.0
API_PORT=8000
```
