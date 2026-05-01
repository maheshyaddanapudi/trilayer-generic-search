# Phase 1 MVP — Design Documentation

**Scope:** Metadata + File Upload
**Status:** Design
**Relation to full design:** These documents are a concrete, scoped subset of the
[generic framework design](../../README.md). Every component built here is a direct
implementation of the generic interfaces — the MVP is Phase 1, not a throwaway.

---

## What Phase 1 MVP Covers

### Domain 1 — Metadata
- Source: Adaptive Planning XML export (`data/sample_metadata.xml`)
- Entities: Account (3-level hierarchy), Level, Version, Sheet, Dimension, DimValue
- Trigger: auto-index on startup + manual `POST /domains/metadata/index`
- Use case: "Find recurring revenue accounts", "What are the children of REVENUE?",
  "Which sheets include SAAS_REVENUE?"

### Domain 2 — Documents (File Upload)
- Source: PDF, DOCX, XLSX uploaded via `POST /domains/documents/files/upload`
- Entities: Document, Section
- Trigger: immediate on upload (synchronous, < 10s)
- Use case: "What is the approval policy for capital expenditure?",
  "Find the EMEA expense policy", "Which policy covers vendor onboarding?"

---

## What Is Deferred to Later Phases

| Feature | Phase |
|---|---|
| HR / Org domain | Phase 2 |
| Compliance domain | Phase 2 |
| Multi-domain search / domain routing | Phase 2 |
| CDC / Kafka event streams | Phase 3 (POC 4) |
| Elasticsearch swap | Phase 3 |
| Cross-domain graph linking | Phase 3 |
| Live API response injection into session | Phase 2 |
| Background job queue for large files | Phase 2 |
| LLM evaluation / judge | Phase 2 |
| Scheduled incremental indexing | Phase 2 |

---

## Document Index

| # | Document | What It Covers |
|---|---|---|
| [01](./01-system-architecture.md) | **System Architecture** | MVP container diagram, two-domain deployment |
| [02](./02-high-level-design.md) | **High-Level Design** | Two concrete domains, write + read paths |
| [03](./03-low-level-design.md) | **Low-Level Design** | Concrete plugin configs, breadcrumb templates, MVP API |
| [04](./04-technical-design.md) | **Technical Design** | MVP project structure, build sequence, tech stack |
| [05](./05-class-diagrams.md) | **Class Diagrams** | MetadataPlugin + DocumentPlugin + engine wiring |
| [06](./06-entity-diagrams.md) | **Entity Diagrams** | Metadata graph + Document graph entity models |
| [07](./07-sequence-diagrams.md) | **Sequence Diagrams** | Startup ingest, file upload, metadata search, doc search |
| [08](./08-flow-diagrams.md) | **Flow Diagrams** | MVP write path, read path, breadcrumb generation per domain |
| [09](./09-testing-report.md) | **Testing Report** | 5 functional TCs + 47 adversarial tests, 3-model comparison, bug log, Phase 1 readiness |

---

## MVP Build Sequence

```
Step 1 — Generic engine core
         src/models/core.py          (RawEntity, MetadataChunk, SearchResult, ParsedIntent)
         src/domain/                 (all interfaces + DomainRegistry)
         src/indexers/               (VectorIndexWriter, LuceneIndexWriter, GraphIndexWriter)
         src/aggregation/            (RRFAggregator, GraphBoostingAggregator)
         src/llm/                    (LLMClient, AnthropicClient, IntentParser, Synthesizer)
         src/search/orchestrator.py  (LangGraph pipeline)

Step 2 — Metadata plugin
         plugins/metadata/plugin.py
         plugins/metadata/connector.py   (XMLFileConnector)
         Register domain, test with sample_metadata.xml

Step 3 — Document plugin
         plugins/documents/plugin.py
         src/connectors/file_system.py   (PDF/DOCX/XLSX extraction)
         POST /domains/documents/files/upload endpoint

Step 4 — API surface
         src/api/routes.py           (search, index, upload, health)
         src/main.py                 (startup lifecycle)

Step 5 — Tests + Docker
         tests/                      (unit + integration)
         docker-compose.yml          (app + neo4j + postgres)
```
