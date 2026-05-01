# MVP 10 — Demo Playbook

**Target duration:** 3–5 minutes  
**Audience:** Technical stakeholders, product sponsors  
**Format:** Terminal + talking points (no slides required)

---

## Intro Script (30 seconds)

> "Enterprise data lives in at least three different shapes — structured metadata like
> account hierarchies, unstructured documents like policies and SOPs, and the
> relationships between them. Finding anything across all three today means separate
> tools, manual joins, and still getting incomplete answers.
>
> This POC shows a single search API that spans all three layers at once: semantic
> vector search, keyword search, and graph traversal — fused together, intent-parsed
> by an LLM, and synthesized into a grounded natural-language answer.
> Let me show you how it works."

---

## Step 1 — Architecture in 60 Seconds

> "Before we touch the terminal, here is what happens every time a query comes in."

```
┌─────────────────────────────────────────────────────────────────────┐
│                      QUERY PIPELINE                                 │
│                                                                     │
│  User Query                                                         │
│      │                                                              │
│      ▼                                                              │
│  ┌──────────────────────────────────────┐                           │
│  │  IntentParser  (LLM — Haiku/Sonnet)  │                           │
│  │  · Classifies: LOOKUP / TRAVERSAL /  │                           │
│  │    DISCOVERY                         │                           │
│  │  · Expands query to 3-8 keywords     │                           │
│  │  · Extracts entity hint              │                           │
│  │  · Generates Cypher hints            │                           │
│  └─────────────────┬────────────────────┘                           │
│                    │  ParsedIntent                                   │
│         ┌──────────┴──────────┐                                     │
│         │   Triple Search     │  (all three run in parallel)        │
│         │                     │                                     │
│  ┌──────▼──────┐ ┌─────▼────┐ ┌──────▼──────┐                      │
│  │  PGVector   │ │  Whoosh  │ │    Neo4j    │                      │
│  │  (semantic  │ │  (BM25F  │ │  (graph     │                      │
│  │   cosine)   │ │  keyword)│ │  traversal) │                      │
│  └──────┬──────┘ └─────┬────┘ └──────┬──────┘                      │
│         └──────────────┴─────────────┘                             │
│                         │  Ranked result lists                      │
│                         ▼                                           │
│              ┌──────────────────────┐                               │
│              │  RRF Aggregator      │  score = Σ 1/(60 + rank)      │
│              │  + Graph Boost       │  neighbours of top hits +1.5x │
│              └──────────┬───────────┘                               │
│                         │  Top-K fused breadcrumbs                  │
│                         ▼                                           │
│              ┌──────────────────────┐                               │
│              │  Synthesizer         │                               │
│              │  (LLM — Haiku)       │                               │
│              │  Grounded answer,    │                               │
│              │  cited to breadcrumbs│                               │
│              └──────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────┘

DATA INGESTION (write path — runs at startup or on upload)

  XML metadata ──► XMLFileConnector ──┐
  PDF / DOCX   ──► FileSystemConnector─┤
  (any source) ──► SourceConnector ABC ┘
                         │
              ┌──────────┴──────────────┐
              │   IngestionOrchestrator  │
              └──────────┬──────────────┘
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    VectorIndexWriter  LuceneIndex  GraphIndexWriter
    (PGVector HNSW)    Writer       (Neo4j)
                       (Whoosh)
```

> "Every entity — whether it's an account from an XML export or a section from a DOCX —
> becomes a breadcrumb: a structured text record that captures its identity, position in
> the hierarchy, and key attributes. That breadcrumb is what gets embedded, indexed, and
> handed to the synthesizer."

---

## Step 2 — Start the System and Verify Health (20 seconds)

```bash
# 1. Start backing services (one-time per session)
service postgresql start
/opt/neo4j-community-5.26.0/bin/neo4j start

# 2. Start the API server
export ANTHROPIC_API_KEY=<your-key>
uvicorn src.main:app --host 0.0.0.0 --port 8000 &

# 3. Confirm all three layers are live
curl -s http://localhost:8000/health | python3 -m json.tool
```

**Expected output — all layers green, both domains indexed:**
```json
{
  "status": "ok",
  "neo4j_ok": true,
  "vector_ok": true,
  "lucene_ok": true,
  "metadata_domain": true,
  "documents_domain": true,
  "metadata":  { "registered": true, "indexed": true, "chunk_count": 33 },
  "documents": { "registered": true, "indexed": true, "chunk_count": 84 }
}
```

> "33 metadata chunks auto-indexed at startup from the Adaptive Planning XML export.
> Documents domain registered and ready. Both domains, three indexes, one endpoint."

---

## Step 3 — Upload a Document (30 seconds)

> "Domain 2 is document-driven. You upload a file, it's parsed, chunked, embedded,
> keyword-indexed, and graph-nodded — all in under a second."

```bash
curl -s -X POST http://localhost:8000/domains/documents/files/upload \
  -F "file=@data_retention_policy.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  | python3 -m json.tool
```

**Expected output:**
```json
{
  "doc_id": "32a77951-04b1-4366-bdfe-d1f58fcdecf2",
  "title": "data_retention_policy",
  "sections_indexed": 6,
  "vector_docs": 7,
  "lucene_docs": 7,
  "graph_nodes": 7,
  "duration_ms": 187.8,
  "file_size_bytes": 37172
}
```

> "6 sections, 7 nodes across all three indexes in under 200 milliseconds.
> PDF, DOCX, and XLSX are all supported — the connector handles extraction,
> the domain plugin defines how sections map to graph nodes."

---

## Step 4 — Inspect What Was Created (45 seconds)

### 4a. PostgreSQL — vector embeddings

> "Every entity gets a 384-dimensional embedding stored in PGVector with an HNSW index
> for fast cosine similarity search."

```bash
PGPASSWORD=tgs psql -h localhost -U tgs -d tgs -c "
SELECT domain_id, entity_type, count(*) AS chunks
FROM metadata_chunks
GROUP BY domain_id, entity_type
ORDER BY domain_id, entity_type;"
```

**Expected output:**
```
 domain_id | entity_type | chunks
-----------+-------------+--------
 documents | Document    |     12
 documents | Section     |     72
 metadata  | Account     |     17
 metadata  | DimValue    |      6
 metadata  | Dimension   |      2
 metadata  | Level       |      3
 metadata  | Sheet       |      2
 metadata  | Version     |      3
```

```bash
# See a sample breadcrumb and confirm embedding exists
PGPASSWORD=tgs psql -h localhost -U tgs -d tgs -c "
SELECT chunk_id, entity_type,
       left(breadcrumb, 90) AS breadcrumb_preview,
       vector_dims(embedding)  AS embedding_dims
FROM   metadata_chunks
WHERE  domain_id = 'metadata' AND entity_type = 'Account'
LIMIT  4;"
```

### 4b. Neo4j — knowledge graph

> "The graph layer stores entities as typed nodes and relationships between them.
> Here are the node counts by label:"

```bash
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC"}' \
  | python3 -m json.tool
```

**Expected output:**
```json
[
  { "label": "Chunk_documents", "count": 77 },
  { "label": "doc_Section",     "count": 66 },
  { "label": "Chunk_metadata",  "count": 33 },
  { "label": "meta_Account",    "count": 17 },
  { "label": "doc_Document",    "count": 11 },
  { "label": "meta_DimValue",   "count":  6 },
  ...
]
```

> "And the relationships — this is what makes traversal queries possible:"

```bash
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY count DESC"}' \
  | python3 -m json.tool
```

**Expected output:**
```json
[
  { "relationship": "PARENT_OF",        "count": 10 },
  { "relationship": "INCLUDES_ACCOUNT", "count":  9 },
  { "relationship": "LINKED_TO",        "count":  2 },
  { "relationship": "USES_VERSION",     "count":  2 },
  { "relationship": "USES_LEVEL",       "count":  2 }
]
```

> "Sheets link to accounts via INCLUDES_ACCOUNT. Accounts link to parents via PARENT_OF.
> These edges are what power traversal queries — 'children of REVENUE', 'ancestor path of
> PROFESSIONAL_SERVICES' — without the LLM needing to know the hierarchy at inference time."

```bash
# Show the sheet → account membership graph
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH (s:meta_Sheet)-[:INCLUDES_ACCOUNT]->(a:meta_Account) RETURN s.name AS sheet, collect(a.code) AS accounts"}' \
  | python3 -m json.tool
```

**Expected output:**
```json
[
  { "sheet": "PL_Summary",     "accounts": ["NET_INCOME","OPEX","GROSS_PROFIT","COGS","REVENUE"] },
  { "sheet": "Revenue_Detail", "accounts": ["SUPPORT_REVENUE","PROFESSIONAL_SERVICES","LICENSE_REVENUE","SAAS_REVENUE"] }
]
```

---

## Step 5 — Search Demos (90 seconds)

### 5a. Metadata domain only — graph traversal

> "Scope the search to metadata only. The LLM classifies this as a graph traversal
> and the system walks the PARENT_OF edges to find children."

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query":  "What are the children of REVENUE?",
    "domain": "metadata",
    "top_k":  3
  }' | python3 -m json.tool
```

**Key fields to highlight:**
```json
{
  "intent": {
    "query_type":     "TRAVERSAL",
    "confidence":     0.95,
    "entity_hint":    "REVENUE",
    "expanded_query": "children of REVENUE account hierarchy"
  },
  "synthesis": "The children of REVENUE are:\n1. SVC_REVENUE (Service Revenue)\n2. PROD_REVENUE (Product Revenue)\n..."
}
```

> "Confidence 0.95 TRAVERSAL. The intent parser identified REVENUE as the root entity,
> generated a Cypher hint, and the graph layer walked the edges. Two children found,
> answer grounded to the breadcrumbs — no hallucination of values that don't exist."

---

### 5b. Documents domain only — policy lookup

> "Now scope to documents only. Same API, different domain."

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query":  "What is the data retention period for financial records?",
    "domain": "documents",
    "top_k":  3
  }' | python3 -m json.tool
```

**Key fields to highlight:**
```json
{
  "intent": {
    "query_type":  "DISCOVERY",
    "confidence":  0.75
  },
  "synthesis": "The data retention period for financial records is a minimum of 7 years per SOX compliance requirements. Budget and forecast versions must be archived for 5 years..."
}
```

> "Answer sourced entirely from the uploaded policy document. The system found the right
> section via semantic embedding — even though the query used 'financial records' and
> the document uses 'revenue accounts'."

---

### 5c. Full scope — cross-domain join (the key differentiator)

> "Now remove the domain filter entirely. The query spans both domains simultaneously.
> Watch what happens."

```bash
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query":  "What is the data retention policy for ARR accounts?",
    "top_k":  5
  }' | python3 -m json.tool
```

**Key fields to highlight:**
```json
{
  "intent": {
    "query_type":     "DISCOVERY",
    "confidence":     0.75,
    "entity_hint":    "SAAS_REVENUE",
    "expanded_query": "data retention policy ARR SAAS_REVENUE accounts"
  },
  "results": [
    { "domain_id": "documents", "entity_type": "Section",  "source": "vector" },
    { "domain_id": "documents", "entity_type": "Section",  "source": "lucene" },
    { "domain_id": "metadata",  "entity_type": "Account",  "source": "graph"  },
    ...
  ],
  "synthesis": "ARR accounts are subject to mandatory 7-year retention. Monthly reporting from the PL_Summary sheet must be archived quarterly..."
}
```

> "The result set mixes metadata entities and document sections — fused by RRF into a
> single ranked list. The synthesizer joins them: 'ARR is this account, and this is what
> the policy says about it.' That join happened with zero custom integration code."

---

## Step 6 — Plugins and Extensibility (30 seconds)

> "Let me show you the seam where you extend this to any new data source."

```
plugins/
├── metadata/
│   ├── plugin.py      ← entity types, graph schema, breadcrumb templates,
│   │                    intent prompt config — all in one file
│   └── connector.py   ← reads Adaptive Planning XML, yields RawEntity objects
│
└── documents/
    ├── plugin.py      ← Document + Section entity types, graph schema
    └── (connector)    ← FileSystemConnector: PDF/DOCX/XLSX → Section chunks
```

> "Adding a new data source — say, Salesforce opportunities, an HR system, or a
> Confluence wiki — is four steps:"

```
1.  Write a SourceConnector    →  fetch records, yield RawEntity objects
                                   (one method: stream_entities())

2.  Write a plugin.py          →  define entity types, graph schema,
                                   breadcrumb templates, and search examples
                                   for the LLM intent prompt

3.  Register the domain        →  registry.register(build_my_domain())
    in src/main.py                 (one line)

4.  Done — the engine handles the rest:
     · three-layer indexing
     · RRF fusion with existing domains
     · cross-domain synthesis at query time
```

> "No changes to the search engine, the aggregation pipeline, the LLM layer, or the API.
> The plugin boundary is clean and explicit."

**Connectors already in this POC:**

| Connector | File | Reads |
|---|---|---|
| `XMLFileConnector` | `src/connectors/xml_file.py` | Adaptive Planning XML exports |
| `FileSystemConnector` | `src/connectors/file_system.py` | PDF, DOCX, XLSX uploads |

**LLM providers already wired:**

| Provider | Client | Switch |
|---|---|---|
| Anthropic (Haiku / Sonnet / Opus) | `src/llm/client.py` | `LLM_PROVIDER=anthropic` |
| Ollama (Gemma, Llama, Mistral, …) | `src/llm/ollama_client.py` | `LLM_PROVIDER=ollama` |
| OpenAI / Gemini | Write ~50-line client | Add branch in `factory.py` |

---

## Step 7 — Closing (20 seconds)

> "What this achieves today:
>
> — A single search endpoint that spans structured metadata, unstructured documents,
>   and the graph relationships between them.
>
> — LLM-driven intent classification that adapts to any query shape — lookup, traversal,
>   or open discovery — without hard-coded query logic.
>
> — Answers grounded in real indexed data, cited to specific entities, with no
>   hallucination of values that don't exist in the index.
>
> — A plugin model that adds a new data source in four steps with zero changes to the
>   engine.
>
> What Phase 1 achieves on top: production hardening — connection pooling, input
> validation, incremental indexing, background ingest jobs — on the exact same tech
> stack. The architecture is not a prototype. It is Phase 1 minus the operational
> envelope."

---

## Quick Reference — All Demo Commands in Order

```bash
# ── SETUP ──────────────────────────────────────────────────────────────────
service postgresql start
/opt/neo4j-community-5.26.0/bin/neo4j start
export ANTHROPIC_API_KEY=<your-key>
uvicorn src.main:app --host 0.0.0.0 --port 8000 &

# ── HEALTH ─────────────────────────────────────────────────────────────────
curl -s http://localhost:8000/health | python3 -m json.tool

# ── UPLOAD DOCUMENT ────────────────────────────────────────────────────────
curl -s -X POST http://localhost:8000/domains/documents/files/upload \
  -F "file=@data_retention_policy.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  | python3 -m json.tool

# ── INSPECT: VECTORS ───────────────────────────────────────────────────────
PGPASSWORD=tgs psql -h localhost -U tgs -d tgs -c \
  "SELECT domain_id, entity_type, count(*) FROM metadata_chunks GROUP BY 1,2 ORDER BY 1,2;"

# ── INSPECT: GRAPH NODES ───────────────────────────────────────────────────
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC"}' \
  | python3 -m json.tool

# ── INSPECT: GRAPH RELATIONSHIPS ───────────────────────────────────────────
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH ()-[r]->() RETURN type(r) AS relationship, count(r) AS count ORDER BY count DESC"}' \
  | python3 -m json.tool

# ── INSPECT: SHEET → ACCOUNT MEMBERSHIP ───────────────────────────────────
curl -s -X POST http://localhost:8000/debug/cypher \
  -H "Content-Type: application/json" \
  -d '{"cypher": "MATCH (s:meta_Sheet)-[:INCLUDES_ACCOUNT]->(a:meta_Account) RETURN s.name AS sheet, collect(a.code) AS accounts"}' \
  | python3 -m json.tool

# ── SEARCH 1: Metadata only — traversal ────────────────────────────────────
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the children of REVENUE?", "domain": "metadata", "top_k": 3}' \
  | python3 -m json.tool

# ── SEARCH 2: Documents only — policy lookup ───────────────────────────────
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the data retention period for financial records?", "domain": "documents", "top_k": 3}' \
  | python3 -m json.tool

# ── SEARCH 3: Full scope — cross-domain join ───────────────────────────────
curl -s -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the data retention policy for ARR accounts?", "top_k": 5}' \
  | python3 -m json.tool
```

---

## Timing Guide

| Section | Talking Points | Commands | Total |
|---|---|---|---|
| Intro | 30 s | — | 0:30 |
| Architecture diagram | 50 s | — | 1:20 |
| Start + health check | 10 s | 1 curl | 1:30 |
| Upload document | 20 s | 1 curl | 1:50 |
| Inspect vectors (PG) | 20 s | 1 psql | 2:10 |
| Inspect graph (Neo4j) | 35 s | 3 curls | 2:45 |
| Search — metadata only | 20 s | 1 curl | 3:05 |
| Search — documents only | 20 s | 1 curl | 3:25 |
| Search — full scope | 25 s | 1 curl | 3:50 |
| Plugins and extensibility | 30 s | — | 4:20 |
| Closing | 20 s | — | 4:40 |
