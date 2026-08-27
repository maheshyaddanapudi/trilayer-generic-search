# MVP 02 — High-Level Design

---

## 1. Two Domain Plugins at a Glance

```
MetadataPlugin                    DocumentPlugin
───────────────────────                    ──────────────
domain_id: metadata              domain_id: documents
source:    XMLFileConnector                source:    FileSystemConnector
trigger:   startup + POST /index           trigger:   POST /upload (immediate)

Entities:                                  Entities:
  Account  (3-level hierarchy)               Document
  Level                                      Section
  Version
  Sheet                                    Graph:
  Dimension                                  doc_Document -[HAS_SECTION]-> doc_Section
  DimValue                                   doc_Document -[SUPERSEDES]-> doc_Document
                                             doc_Document -[TAGGED_WITH]-> doc_Tag
Graph:
  meta_Account -[PARENT_OF]-> meta_Account    Breadcrumb template:
  meta_Account -[LINKED_TO]-> meta_Account      [Title §N] | Section | doc:[DocTitle] |
  meta_Sheet -[INCLUDES_ACCOUNT]->              [Summary] | owner=[X]; effective=[Y]
    meta_Account
  meta_Sheet -[USES_VERSION]-> meta_Version   Intent emphasis:
  meta_Sheet -[USES_LEVEL]-> meta_Level         Policy text → Vector primary
  meta_Dimension -[HAS_VALUE]-> meta_DimValue   Exact policy codes → Lucene primary
                                            "sections of doc X" → Graph primary
Breadcrumb template:
  [Code] | [Type] | parent:[P] > [GP] |
  [Description] | [key attributes]

Intent emphasis:
  Business terms → Vector primary
  Exact codes (SAAS_REVENUE) → Lucene primary
  "children of X", "what's in sheet Y" → Graph primary
```

---

## 2. Write Path — Metadata

```mermaid
flowchart TD
    A([App startup OR\nPOST /domains/metadata/index]) --> B[XMLFileConnector.fetch_all\ndata/sample_metadata.xml]
    B --> C[lxml DOM parse\nextract Accounts, Levels, Versions,\nSheets, Dimensions, DimValues]
    C --> D[RawEntity stream\n~50 entities from sample XML]
    D --> E[BreadcrumbGenerator\nusing MetadataBreadcrumbTemplate]

    E --> F{Entity has parent?}
    F -->|yes| G[GraphIndexWriter.get_ancestors\nbuild lineage chain]
    F -->|no| H[root entity]
    G --> I[breadcrumb with full parent chain]
    H --> I

    I --> J{Entity type}
    J -->|Account| K[MetadataChunk\nAccount breadcrumb\nwith parent lineage chain]
    J -->|Version| L[MetadataChunk\nVersion breadcrumb\nwith date window]
    J -->|Sheet| M[MetadataChunk\nSheet breadcrumb\nwith account list]

    K --> N[MetadataChunk]
    L --> N
    M --> N

    N --> O[Fan-out — all in parallel]
    O --> P[VectorIndexWriter.index\nencode breadcrumb → 384-dim vector]
    O --> Q[LuceneIndexWriter.index\ntokenize into Whoosh schema]
    O --> R[GraphIndexWriter.index\nMERGE meta_Account node\nMERGE PARENT_OF edges]
```

---

## 3. Write Path — Document Upload

```mermaid
flowchart TD
    A([POST /domains/documents/files/upload\nbinary file multipart]) --> B{MIME check}
    B -->|PDF| C[pdfminer.six\ntext extraction]
    B -->|DOCX| D[python-docx\ntext extraction]
    B -->|XLSX| E[openpyxl\nsheet extraction]
    B -->|other| Z([413 / 415 error])

    C --> F[Section detector\nheading heuristics\ne.g. §1 §2 or H1 H2 tags]
    D --> F
    E --> G[Row-group detector\nsheet name = section name]

    F --> H[RawEntity per section\nparent = document]
    G --> H

    H --> I[BreadcrumbGenerator\nusing DocumentBreadcrumbTemplate]
    I --> J[MetadataChunk\nSection breadcrumb\nwith document lineage]

    J --> K[MetadataChunk]
    K --> L[Fan-out — all in parallel]
    L --> M[VectorIndexWriter.index]
    L --> N[LuceneIndexWriter.index]
    L --> O[GraphIndexWriter.index\ndoc_Document node\ndoc_Section nodes\nHAS_SECTION edges]

    L --> P[IngestionResult\nsections_indexed + latency]
    P --> Q([200 OK — file immediately searchable])
```

---

## 4. Read Path — Both Domains

```mermaid
flowchart TD
    A([POST /search]) --> B{domain in request?}
    B -->|metadata| C[Load MetadataPlugin config]
    B -->|documents| D[Load DocumentPlugin config]
    B -->|null — all domains| E2[Load all registered domain configs]

    C --> E[LangGraph SearchOrchestrator.run]
    D --> E
    E2 --> E

    E --> F[Node 1: parse_intent\nIntentParser + Claude Haiku\ndomain-specific system prompt]

    F --> J[Node 2: triple_dispatch\nasyncio.gather × 3]
    J --> K[VectorSearch\nPGVector HNSW\ndomain partition]
    J --> L[LuceneSearch\nWhoosh index\ndomain prefix filter]
    J --> M[GraphSearch\nNeo4j Cypher\ndomain namespace: meta_ or doc_]

    K --> O[Node 3: aggregate]
    L --> O
    M --> O

    O --> P[RRFAggregator\n3-source merge]
    P --> Q[GraphBoostingAggregator\nboost graph neighbours]

    Q --> S[Node 4: synthesize\nSynthesizer + Claude Sonnet\ntop-K breadcrumbs injected]
    S --> T[Grounded NL answer\nciting fully qualified names]
    T --> U([SearchResponse])
```

---

## 5. Concrete Query Examples

### Metadata Queries

| Query | Type | Leading Index | Example Result |
|---|---|---|---|
| "show me recurring revenue accounts" | DISCOVERY | Vector | SAAS_REVENUE, PROD_REVENUE |
| "SAAS_REVENUE" | LOOKUP | Lucene | SAAS_REVENUE breadcrumb (exact) |
| "children of REVENUE" | TRAVERSAL | Graph | PROD_REVENUE, SVC_REVENUE |
| "what accounts are in PL_Summary?" | TRAVERSAL | Graph | REVENUE, COGS, GROSS_PROFIT, OPEX, NET_INCOME |
| "budget versions" | DISCOVERY | Vector | BUDGET, Q2_FORECAST |

### Document Queries

| Query | Type | Leading Index | Example Result |
|---|---|---|---|
| "capital expenditure approval" | DISCOVERY | Vector | CapEx Policy §4.2 |
| "CapEx Policy Rev3" | LOOKUP | Lucene | Exact document match |
| "sections of the expense policy" | TRAVERSAL | Graph | All HAS_SECTION children |
| "vendor onboarding procedures" | DISCOVERY | Vector | Procurement Policy §2, Vendor Guide §1 |

---

## 6. Aggregation in MVP

```
3 result lists enter AggregationPipeline:
  vector_results  (up to 10) ─┐
  lucene_results  (up to 10) ─┤→ RRFAggregator → rrf_merged (top 10)
  graph_results   (up to 10) ─┘

rrf_merged → GraphBoostingAggregator
  Takes top-3 Lucene results, fetches 1-hop graph neighbours
  Boosts neighbours found in rrf_merged by 1.5×

Final top-K → Synthesizer (Claude Sonnet)
  System prompt: "Answer ONLY using the provided breadcrumbs."
  Response cites: fully qualified name + domain path
```

---

## 7. Synthesis Output Format

### Metadata Answer

```
Found 3 relevant accounts for "recurring revenue":

1. SAAS_REVENUE (Account › PROD_REVENUE › REVENUE)
   SaaS Subscription Revenue tracking ARR/MRR.
   Billing: recurring_monthly. Metric: arr.
   Found in: Revenue_Detail sheet (ACTUAL, BUDGET, Q2_FORECAST versions).

2. PROD_REVENUE (Account › REVENUE)
   Total Product Revenue. Parent of SAAS_REVENUE and LICENSE_REVENUE.

3. LICENSE_REVENUE (Account › PROD_REVENUE › REVENUE)
   Perpetual License Revenue. Billing: one_time. Metric: tlv.

Sources: metadata index (vector + lucene + graph)
```

### Document Answer

```
Found the capital expenditure approval policy:

CapEx Policy Rev3 §4.2 — Approval Thresholds (Policy Section)
Document: Capital Expenditure Policy Rev3
Owner: CFO Office | Effective: 2026-01-01

"Any capital expenditure over $50,000 requires CFO sign-off
within 5 business days of submission."

Related sections in the same document:
• §4.1 — CapEx Definition and Scope
• §4.3 — Expedited Approval Process

Sources: documents index (vector + lucene + graph)
```
