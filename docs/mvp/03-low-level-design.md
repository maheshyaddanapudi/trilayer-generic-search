# MVP 03 — Low-Level Design

---

## 1. MetadataPlugin — Concrete Configuration

### 1.1 Entity Type Registry

```python
# plugins/metadata/plugin.py

METADATA_ENTITY_TYPES = EntityTypeRegistry()

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Account",
    id_field="code",
    display_field="code",
    description_field="desc",
    properties=[
        PropertyDefinition("code",             FieldType.STRING,  required=True),
        PropertyDefinition("desc",             FieldType.STRING,  required=True),
        PropertyDefinition("type",             FieldType.STRING),   # standard/cube/model
        PropertyDefinition("parent",           FieldType.STRING),
        PropertyDefinition("attributes",       FieldType.LIST),
    ],
    parent_type="Account",
    searchable_fields=["code", "desc"],
))

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Level",
    id_field="code", display_field="code", description_field="desc",
    properties=[PropertyDefinition("code", FieldType.STRING, required=True),
                PropertyDefinition("desc", FieldType.STRING, required=True)],
))

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Version",
    id_field="code", display_field="code", description_field="desc",
    properties=[PropertyDefinition("code",       FieldType.STRING, required=True),
                PropertyDefinition("desc",       FieldType.STRING, required=True),
                PropertyDefinition("start_time", FieldType.DATE),
                PropertyDefinition("end_time",   FieldType.DATE)],
))

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Sheet",
    id_field="name", display_field="name", description_field="name",
    properties=[PropertyDefinition("name", FieldType.STRING, required=True),
                PropertyDefinition("type", FieldType.STRING)],
))

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Dimension",
    id_field="name", display_field="name", description_field="name",
    properties=[PropertyDefinition("name", FieldType.STRING, required=True)],
))

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="DimValue",
    id_field="name", display_field="name", description_field="value",
    properties=[PropertyDefinition("name",      FieldType.STRING, required=True),
                PropertyDefinition("value",     FieldType.STRING, required=True),
                PropertyDefinition("dimension", FieldType.STRING)],
    parent_type="Dimension",
))
```

### 1.2 Graph Schema

```python
METADATA_GRAPH_SCHEMA = GraphSchema(
    domain_namespace="meta",          # Neo4j labels: meta_Account, meta_Sheet, etc.
    node_labels={
        "Account":   NodeLabel("meta_Account",   "Account",   "code",  ["code", "desc"]),
        "Level":     NodeLabel("meta_Level",     "Level",     "code",  ["code", "desc"]),
        "Version":   NodeLabel("meta_Version",   "Version",   "code",  ["code", "desc"]),
        "Sheet":     NodeLabel("meta_Sheet",     "Sheet",     "name",  ["name"]),
        "Dimension": NodeLabel("meta_Dimension", "Dimension", "name",  ["name"]),
        "DimValue":  NodeLabel("meta_DimValue",  "DimValue",  "name",  ["name", "value"]),
    },
    relationships=[
        RelationshipDefinition("PARENT_OF",         "meta_Account",   "meta_Account",   directed=True,  inverse_name="CHILD_OF"),
        RelationshipDefinition("LINKED_TO",         "meta_Account",   "meta_Account",   directed=False),
        RelationshipDefinition("INCLUDES_ACCOUNT",  "meta_Sheet",     "meta_Account",   directed=True),
        RelationshipDefinition("USES_VERSION",      "meta_Sheet",     "meta_Version",   directed=True),
        RelationshipDefinition("USES_LEVEL",        "meta_Sheet",     "meta_Level",     directed=True),
        RelationshipDefinition("HAS_VALUE",         "meta_Dimension", "meta_DimValue",  directed=True),
    ],
    traversal_rules=[
        TraversalRule("PARENT_OF",        TraversalDirection.OUTBOUND, max_depth=3, use_for_boost=True),
        TraversalRule("LINKED_TO",        TraversalDirection.BOTH,     max_depth=1, use_for_boost=True),
        TraversalRule("INCLUDES_ACCOUNT", TraversalDirection.INBOUND,  max_depth=1, use_for_boost=False),
    ],
    boost_edges=["PARENT_OF", "LINKED_TO"],
)
```

### 1.3 Breadcrumb Template

```python
METADATA_BREADCRUMB = TemplateBreadcrumbTemplate(
    identity_slot=BreadcrumbSlot(field_path="entity_id"),
    description_slot=BreadcrumbSlot(field_path="description"),
    attribute_slots=[
        BreadcrumbSlot(field_path="properties.type",         label=None),
        BreadcrumbSlot(field_path="properties.metric",       label="metric="),
        BreadcrumbSlot(field_path="properties.billing_type", label="billing="),
        BreadcrumbSlot(field_path="properties.formula",      label="formula="),
        BreadcrumbSlot(field_path="properties.start_time",   label="from:"),
        BreadcrumbSlot(field_path="properties.end_time",     label="to:"),
    ],
    lineage_depth=2,
    separator=" | ",
    max_total_length=512,
)

# Concrete outputs:
# SAAS_REVENUE | Account | parent:PROD_REVENUE > REVENUE | SaaS Subscription Revenue (ARR/MRR) | metric=arr; billing=recurring_monthly
# ACTUAL | Version | Metadata | Actuals – recorded financial results | from:2026-01-01; to:2026-03-31
# PL_Summary | Sheet | Metadata | standard planning sheet | standard
# EMEA | DimValue | parent:Region | Europe, Middle East and Africa
```

### 1.4 Intent Prompt Config

```python
METADATA_INTENT_PROMPT = IntentPromptConfig(
    entity_type_descriptions={
        "Account":   "financial accounts like REVENUE, COGS, SAAS_REVENUE, NET_INCOME, OPEX",
        "Level":     "aggregation granularity: CORPORATE, DIVISION, DEPARTMENT",
        "Version":   "planning scenarios: ACTUAL, BUDGET, Q2_FORECAST",
        "Sheet":     "planning sheets: PL_Summary, Revenue_Detail, COGS_Detail",
        "Dimension": "analytical dimensions: Region, Product, Department",
        "DimValue":  "dimension members: NA, EMEA, APAC, ENTERPRISE, SMB",
    },
    synonym_expansion_map={
        "revenue":     ["arr", "mrr", "income", "sales", "REVENUE", "PROD_REVENUE", "SVC_REVENUE"],
        "cost":        ["cogs", "expense", "COGS", "OPEX", "DIRECT_MATERIAL", "DIRECT_LABOR"],
        "profit":      ["gross profit", "net income", "GROSS_PROFIT", "NET_INCOME"],
        "saas":        ["subscription", "arr", "recurring", "SAAS_REVENUE"],
        "budget":      ["plan", "forecast", "BUDGET", "Q2_FORECAST"],
        "actual":      ["realized", "recorded", "ACTUAL"],
        "headcount":   ["HC_EXPENSE", "salary", "labor", "DIRECT_LABOR"],
        "engineering": ["ENGINEERING", "product", "tech"],
    },
    query_type_examples={
        "lookup":    ["show me SAAS_REVENUE", "what is ACTUAL version", "find PL_Summary sheet"],
        "traversal": ["children of REVENUE", "what accounts roll up to OPEX",
                      "what is in the Revenue_Detail sheet", "parent of SAAS_REVENUE"],
        "discovery": ["recurring revenue accounts", "where is ARR tracked",
                      "headcount-related costs", "Q2 planning scenarios"],
    },
    cypher_hint_patterns={
        "children":  "MATCH (a:meta_Account)-[:PARENT_OF]->(c:meta_Account) WHERE a.code = $code RETURN c",
        "ancestors": "MATCH (a:meta_Account)-[:PARENT_OF*]->(c:meta_Account) WHERE c.code = $code RETURN a",
        "sheet_accounts": "MATCH (s:meta_Sheet)-[:INCLUDES_ACCOUNT]->(a:meta_Account) WHERE s.name = $name RETURN a",
        "linked":    "MATCH (a:meta_Account)-[:LINKED_TO]-(b:meta_Account) WHERE a.code = $code RETURN b",
    },
    grounding_format_description="Sheet > Version/Level > Account hierarchy path",
)
```

### 1.5 Full Domain Config

```python
METADATA_DOMAIN = DomainConfig(
    domain_id="metadata",
    display_name="Financial Planning Metadata",
    description="Accounts, Versions, Sheets, Levels, and Dimensions from the financial planning system",
    connector=XMLFileConnector(
        file_path=Path(settings.metadata_file),
        entity_types=METADATA_ENTITY_TYPES,
    ),
    entity_types=METADATA_ENTITY_TYPES,
    graph_schema=METADATA_GRAPH_SCHEMA,
    breadcrumb_template=METADATA_BREADCRUMB,
    intent_prompt=METADATA_INTENT_PROMPT,
    trigger_config=TriggerConfig(
        mode=TriggerMode.MANUAL,
        full_reindex_on_startup=True,
    ),
    rrf_k=60,
    graph_boost_factor=1.5,
    graph_boost_top_n=3,
    default_top_k=10,
    namespace_isolated=True,
)
```

---

## 2. DocumentPlugin — Concrete Configuration

### 2.1 Entity Type Registry

```python
DOCUMENT_ENTITY_TYPES = EntityTypeRegistry()

DOCUMENT_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Document",
    id_field="doc_id",
    display_field="title",
    description_field="summary",
    properties=[
        PropertyDefinition("doc_id",       FieldType.STRING, required=True),
        PropertyDefinition("title",        FieldType.STRING, required=True),
        PropertyDefinition("doc_type",     FieldType.STRING),  # policy/procedure/guide/sop
        PropertyDefinition("status",       FieldType.STRING),  # draft/published/superseded
        PropertyDefinition("effective_date", FieldType.DATE),
        PropertyDefinition("owner",        FieldType.STRING),
        PropertyDefinition("version",      FieldType.STRING),
        PropertyDefinition("tags",         FieldType.LIST),
    ],
    searchable_fields=["title", "doc_type", "tags"],
))

DOCUMENT_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Section",
    id_field="section_id",
    display_field="heading",
    description_field="content_summary",
    properties=[
        PropertyDefinition("section_id",      FieldType.STRING, required=True),
        PropertyDefinition("doc_id",          FieldType.STRING, required=True),
        PropertyDefinition("heading",         FieldType.STRING, required=True),
        PropertyDefinition("order_index",     FieldType.NUMBER),
        PropertyDefinition("content_summary", FieldType.STRING),
        PropertyDefinition("page_number",     FieldType.NUMBER),
    ],
    parent_type="Document",
    searchable_fields=["heading", "content_summary"],
))
```

### 2.2 Graph Schema

```python
DOCUMENT_GRAPH_SCHEMA = GraphSchema(
    domain_namespace="doc",
    node_labels={
        "Document": NodeLabel("doc_Document", "Document", "doc_id", ["title", "doc_type"]),
        "Section":  NodeLabel("doc_Section",  "Section",  "section_id", ["heading"]),
    },
    relationships=[
        RelationshipDefinition("HAS_SECTION", "doc_Document", "doc_Section",  directed=True),
        RelationshipDefinition("SUPERSEDES",  "doc_Document", "doc_Document", directed=True,
                               inverse_name="SUPERSEDED_BY"),
        RelationshipDefinition("TAGGED_WITH", "doc_Document", "doc_Tag",      directed=True),
    ],
    traversal_rules=[
        TraversalRule("HAS_SECTION", TraversalDirection.OUTBOUND, max_depth=1, use_for_boost=True),
        TraversalRule("SUPERSEDES",  TraversalDirection.OUTBOUND, max_depth=2, use_for_boost=False),
    ],
    boost_edges=["HAS_SECTION"],
)
```

### 2.3 Breadcrumb Template

```python
DOCUMENT_BREADCRUMB = TemplateBreadcrumbTemplate(
    identity_slot=BreadcrumbSlot(field_path="name"),         # "CapEx Policy Rev3 §4.2"
    description_slot=BreadcrumbSlot(field_path="description"),
    attribute_slots=[
        BreadcrumbSlot(field_path="properties.owner",          label="owner="),
        BreadcrumbSlot(field_path="properties.effective_date", label="effective="),
        BreadcrumbSlot(field_path="properties.status",         label=None),
        BreadcrumbSlot(field_path="properties.tags",           label="tags="),
    ],
    lineage_depth=1,        # "doc:[DocTitle]" is sufficient; no deeper hierarchy
    separator=" | ",
    max_total_length=512,
)

# Concrete outputs:
# CapEx Policy Rev3 §4.2 | Section | doc:Capital Expenditure Policy Rev3 | Any CapEx over $50k requires CFO approval | owner=CFO Office; effective=2026-01-01
# Capital Expenditure Policy Rev3 | Document | Financial Policies | Corporate capital expenditure policy | owner=CFO Office; effective=2026-01-01; policy
# Vendor Onboarding Guide §2.1 | Section | doc:Vendor Onboarding Guide | Vendor risk assessment required for all new suppliers over $10k | owner=Procurement; tags=vendor,risk
```

### 2.4 Intent Prompt Config

```python
DOCUMENT_INTENT_PROMPT = IntentPromptConfig(
    entity_type_descriptions={
        "Document": "policy documents, SOPs, guides, procedures — e.g. CapEx Policy, Expense Policy",
        "Section":  "sections within documents — e.g. §4.2 Approval Thresholds",
    },
    synonym_expansion_map={
        "approval":     ["sign-off", "authorization", "delegation", "authority"],
        "expense":      ["expenditure", "cost", "spend", "reimbursement"],
        "vendor":       ["supplier", "contractor", "third-party", "procurement"],
        "policy":       ["procedure", "guideline", "SOP", "standard", "rule"],
        "capital":      ["capex", "investment", "asset", "infrastructure"],
        "travel":       ["T&E", "trip", "accommodation", "airfare"],
        "onboarding":   ["setup", "registration", "enrollment"],
    },
    query_type_examples={
        "lookup":    ["Capital Expenditure Policy Rev3", "find expense policy",
                      "Vendor Onboarding Guide"],
        "traversal": ["sections of the CapEx policy", "what's in the expense guide",
                      "all sections about approval thresholds"],
        "discovery": ["how do I get approval for large purchases",
                      "what is the vendor risk assessment process",
                      "travel reimbursement limits"],
    },
    cypher_hint_patterns={
        "sections":  "MATCH (d:doc_Document)-[:HAS_SECTION]->(s:doc_Section) WHERE d.title CONTAINS $title RETURN s",
        "supersedes": "MATCH (d:doc_Document)-[:SUPERSEDES*]->(old:doc_Document) WHERE d.doc_id = $id RETURN old",
    },
    grounding_format_description="Document Title > §Section heading (owner, effective date)",
)
```

### 2.5 Full Domain Config

```python
DOCUMENT_DOMAIN = DomainConfig(
    domain_id="documents",
    display_name="Policy and Procedure Documents",
    description="Uploaded PDF, DOCX, and XLSX documents — policies, SOPs, guides",
    connector=FileSystemConnector(
        watch_dir=Path(settings.uploads_dir),
        supported_mimes=["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    ),
    entity_types=DOCUMENT_ENTITY_TYPES,
    graph_schema=DOCUMENT_GRAPH_SCHEMA,
    breadcrumb_template=DOCUMENT_BREADCRUMB,
    intent_prompt=DOCUMENT_INTENT_PROMPT,
    trigger_config=TriggerConfig(
        mode=TriggerMode.MANUAL,
        full_reindex_on_startup=False,   # uploads dir starts empty; no startup index
    ),
    rrf_k=60,
    graph_boost_factor=1.4,             # slightly lower — section siblings are less discriminating than account siblings
    graph_boost_top_n=3,
    default_top_k=10,
    namespace_isolated=True,
)
```

---

## 3. MVP API Contract

```
GET  /health                                    System + index health check

# Metadata
POST /domains/metadata/index          Re-index from XML file
GET  /domains/metadata               Domain info + entity counts
POST /search/metadata                Single-domain metadata search

# Documents
POST /domains/documents/files/upload           Upload + immediately index a file
GET  /domains/documents/files                  List indexed files
DELETE /domains/documents/files/{doc_id}       Remove a file and its index entries
GET  /domains/documents                        Domain info + document count
POST /search/documents                         Single-domain document search

# Generic search — null domain = all registered domains
POST /search                                   Search with optional domain filter

# Debug
POST /debug/cypher                             Raw Cypher (dev only)
```

### MVP Search Request

```python
class SearchRequest(BaseModel):
    query: str
    domain: Literal["metadata", "documents"] | None = None  # null = search all domains
    top_k: int = Field(default=10, ge=1, le=20)   # lower cap in MVP
    search_mode: Literal["hybrid", "vector", "lucene", "graph"] = "hybrid"
```

### File Upload Response

```python
class FileUploadResponse(BaseModel):
    doc_id: str
    title: str
    sections_indexed: int
    vector_docs: int
    lucene_docs: int
    graph_nodes: int
    duration_ms: float
    file_size_bytes: int
```

---

## 4. Concrete Breadcrumb Examples

### Metadata — all entity types

```
REVENUE        | Account  | Metadata                           | Total Revenue                              | standard; sign=credit
PROD_REVENUE   | Account  | parent:REVENUE                               | Product Revenue                            | standard; revenue_type=recurring
SAAS_REVENUE   | Account  | parent:PROD_REVENUE > REVENUE                | SaaS Subscription Revenue (ARR/MRR)        | cube; metric=arr; billing=recurring_monthly
LICENSE_REVENUE| Account  | parent:PROD_REVENUE > REVENUE                | Perpetual License Revenue                  | standard; metric=tlv; billing=one_time
COGS           | Account  | Metadata                           | Cost of Goods Sold                         | standard; sign=debit
GROSS_PROFIT   | Account  | Metadata                           | Gross Profit (Revenue minus COGS)          | model; formula=REVENUE - COGS
NET_INCOME     | Account  | Metadata                           | Net Income (Gross Profit minus OpEx)       | model; formula=GROSS_PROFIT - OPEX
ACTUAL         | Version  | Metadata                           | Actuals – recorded financial results       | from:2026-01-01; to:2026-03-31
BUDGET         | Version  | Metadata                           | Annual budget plan approved by finance     | from:2026-01-01; to:2026-12-31
PL_Summary     | Sheet    | Metadata                           | Standard P&L summary sheet                 | standard; accounts:REVENUE,COGS,GROSS_PROFIT,...
CORPORATE      | Level    | Metadata                           | Corporate consolidated view                |
EMEA           | DimValue | parent:Region                                | Europe, Middle East and Africa             |
```

### Documents — concrete examples

```
Capital Expenditure Policy Rev3 | Document | Financial Policies | Corporate CapEx approval policy | owner=CFO Office; effective=2026-01-01; published
CapEx Policy Rev3 §1            | Section  | doc:Capital Expenditure Policy Rev3 | Scope and definitions for capital expenditure | owner=CFO Office; page=1
CapEx Policy Rev3 §4.2          | Section  | doc:Capital Expenditure Policy Rev3 | CapEx over $50k requires CFO sign-off within 5 days | owner=CFO Office; page=8
Expense Reimbursement Policy    | Document | HR Policies | Employee expense submission and reimbursement | owner=HR; effective=2025-07-01; published
Expense Policy §3 — Travel      | Section  | doc:Expense Reimbursement Policy | Economy class required for flights under 6 hours | owner=HR; page=5
```

---

## 5. Error Handling — MVP

| Failure | Behaviour |
|---|---|
| Neo4j unreachable at startup | Log warning; vector + lucene indices still populated; graph search returns `[]` |
| LLM call fails (intent) | Heuristic fallback; `confidence=0.0`; search continues |
| LLM call fails (synthesis) | Return ranked results without synthesis text; `synthesis=""` |
| File upload > 20MB | 413 Request Entity Too Large |
| Unsupported file type | 415 Unsupported Media Type |
| Invalid XML metadata file | 422 with parse error details |
| Domain not registered | 404 with list of registered domains |
