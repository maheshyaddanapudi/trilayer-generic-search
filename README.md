# Trilayer Generic Search (TGS)

Hybrid retrieval over structured metadata and uploaded documents. Every query is answered by three
indexes in parallel — **vector** (pgvector), **keyword** (Whoosh), and **graph** (Neo4j) — and the
result lists are fused with **Reciprocal Rank Fusion**, re-ranked with a **graph-neighbourhood boost**,
and summarised by an LLM into a grounded answer.

The engine is domain-agnostic: each data domain is a plugin (`DomainConfig`) that declares its
connector, entity types, graph schema, breadcrumb template, and intent prompt. Two domains ship
with the MVP: **financial planning metadata** (XML) and **uploaded documents** (PDF/DOCX/XLSX).

> **Status:** Phase 1 MVP. See [Limitations](#limitations) and the design docs in [`docs/`](docs/).

---

## How it works

```mermaid
flowchart LR
    subgraph Ingest
        SRC[Connector<br/>XML file / file upload] --> ENT[RawEntity]
        ENT --> BC[Breadcrumb generator<br/>lineage + attributes]
        BC --> VW[(pgvector<br/>HNSW, cosine)]
        BC --> LW[(Whoosh<br/>per-domain index)]
        ENT --> GW[(Neo4j<br/>nodes + relationships)]
    end

    subgraph Search["Search (LangGraph pipeline)"]
        Q[Query] --> IP[parse_intent<br/>LLM + heuristic fallback]
        IP --> TS{triple_search<br/>parallel}
        TS --> VS[Vector search]
        TS --> KS[Keyword search]
        TS --> GS[Graph search<br/>Cypher hints / CONTAINS]
        VS & KS & GS --> AG[aggregate<br/>RRF + graph boost]
        AG --> SY[synthesize<br/>grounded LLM answer]
    end

    VW -.-> VS
    LW -.-> KS
    GW -.-> GS
    GW -.-> AG
```

**Ingestion.** A connector yields `RawEntity` objects. Each entity is turned into a *breadcrumb* —
a compact text line built from a per-domain template (identity, description, selected attributes,
and up to two levels of ancestor lineage). Breadcrumbs are fanned out to all three indexes; entities
and relationships are also written to Neo4j as typed nodes and edges.

**Search.** `SearchOrchestrator` is a four-node LangGraph `StateGraph`:

1. **`parse_intent`** — the LLM classifies the query as `LOOKUP`, `TRAVERSAL`, or `DISCOVERY`,
   expands it, and may return Cypher hints. If the LLM fails or reports confidence < 0.7, a keyword /
   regex heuristic is used instead.
2. **`triple_search`** — vector, keyword, and graph searches run concurrently
   (`asyncio.gather`); a failure in one index is logged and treated as an empty result list.
3. **`aggregate`** — `RRFAggregator` fuses the lists (`score = Σ 1 / (k + rank + 1)`, default
   `k = 60`), then `GraphBoostingAggregator` multiplies the score of any result that is a 1-hop
   neighbour (`PARENT_OF`, `LINKED_TO`, `HAS_SECTION`) of the top keyword hits (default ×1.5, top 3 seeds).
4. **`synthesize`** — the LLM writes a concise answer constrained to the retrieved breadcrumbs.

## Features

- Three retrieval strategies in one call, fused with RRF and a graph-aware re-rank
- Pluggable domains: connector, entity types, graph schema, breadcrumb template, and intent prompt per domain
- Built-in domains:
  - **metadata** — accounts (3-level hierarchy), levels, versions, sheets, dimensions, and dimension
    values from an XML export ([`data/sample_metadata.xml`](data/sample_metadata.xml)); indexed automatically on startup
  - **documents** — PDF, DOCX, and XLSX uploads (≤ 20 MB) split into document and section entities
- Switchable LLM provider: **Ollama** (local) or **Anthropic**, with separate models for intent parsing and synthesis
- Graceful degradation: if Neo4j is unreachable at startup the app runs with graph search disabled
- `/health` reports per-index status and per-domain indexed chunk counts
- Unit test suite with a 100% coverage gate (`pytest.ini`)

## Tech stack

| Concern | Technology |
|---|---|
| API | FastAPI, Uvicorn, Pydantic v2 / pydantic-settings |
| Orchestration | LangGraph |
| Vector index | PostgreSQL 16 + pgvector (HNSW, cosine), sentence-transformers `all-MiniLM-L6-v2` (384-dim) |
| Keyword index | Whoosh (one index directory per domain) |
| Graph | Neo4j 5 (APOC plugin enabled in Compose) |
| LLM | Ollama (`/api/chat`) or Anthropic |
| Extraction | lxml, pdfminer.six, python-docx, openpyxl |
| Tests | pytest, pytest-asyncio, pytest-cov |

## Getting started

### Prerequisites

- Docker with Docker Compose
- An LLM: either [Ollama](https://ollama.com) running on the host, or an Anthropic API key

### Run with Docker Compose

```bash
git clone https://github.com/maheshyaddanapudi/trilayer-generic-search.git
cd trilayer-generic-search

cp .env.example .env          # then edit LLM settings (see below); .env is git-ignored
docker compose up --build
```

This starts three services:

| Service | Port(s) | Notes |
|---|---|---|
| `tgs-app` | 8000 | FastAPI app; interactive docs at http://localhost:8000/docs |
| `neo4j` | 7474 (browser), 7687 (bolt) | default credentials `neo4j` / `password` |
| `postgres` | 5432 | `pgvector/pgvector:pg16`, database `tgs_db` |

On startup the app creates the pgvector table and HNSW index, pre-creates Neo4j labels, and runs a
full index of `data/sample_metadata.xml`. The first start also downloads the embedding model.

### Configuration

Settings are read from environment variables / `.env` ([`src/config.py`](src/config.py)).
The most relevant ones:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` (`.env.example` sets `ollama`) | `ollama` or `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Compose example uses `http://host.docker.internal:11434` |
| `OLLAMA_INTENT_MODEL` / `OLLAMA_SYNTHESIS_MODEL` | `gemma4:31b` | Any model pulled into Ollama |
| `ANTHROPIC_API_KEY` | placeholder | Required when `LLM_PROVIDER=anthropic` |
| `INTENT_MODEL` / `SYNTHESIS_MODEL` | Anthropic model IDs | Intent and synthesis models |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | `bolt://localhost:7687`, `neo4j`, `password` | Overridden in Compose |
| `POSTGRES_URL` | `postgresql://tgs:tgs_password@localhost:5432/tgs_db` | Overridden in Compose |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |
| `METADATA_FILE` | `./data/sample_metadata.xml` | Metadata XML indexed at startup |
| `RRF_K`, `GRAPH_BOOST_FACTOR`, `GRAPH_BOOST_TOP_N` | `60`, `1.5`, `3` | Fusion and boost tuning |
| `DEBUG_API_TOKEN` | unset | Enables `POST /debug/cypher`; callers must send `Authorization: Bearer <token>`. Unset = endpoint disabled (404) |

If the LLM is unreachable, intent parsing falls back to the heuristic and the `synthesis` field is
returned empty; retrieval still works.

### Run locally (without Docker for the app)

```bash
docker compose up -d neo4j postgres

python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# point at local services instead of the Compose hostnames
export OLLAMA_BASE_URL=http://localhost:11434
uvicorn src.main:app --reload --port 8000
```

## Usage

### Search

```bash
curl -s localhost:8000/search -H 'Content-Type: application/json' -d '{
  "query": "What are the children of REVENUE?",
  "domain": "metadata",
  "top_k": 5
}'
```

The response contains the fused `results` (each with `chunk_id`, `score`, `breadcrumb`, `entity_type`,
`domain_id`, `rank`, and the originating `source`: `vector`, `lucene`, or `graph`), the parsed
`intent`, the LLM `synthesis`, and `latency_ms`. Omit `domain` to search across all domains.

Example queries for the sample data: *"Find recurring revenue accounts"*, *"Which sheets include
SAAS_REVENUE?"*, *"SAAS_REVENUE"*.

### Upload and search a document

```bash
curl -s -F "file=@policy.pdf;type=application/pdf" localhost:8000/domains/documents/files/upload

curl -s localhost:8000/search -H 'Content-Type: application/json' \
  -d '{"query": "approval policy for capital expenditure", "domain": "documents"}'
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Index connectivity and per-domain chunk counts |
| `POST` | `/search` | Hybrid search + synthesis |
| `POST` | `/domains/metadata/index` | Full re-index of the configured metadata file |
| `POST` | `/domains/documents/files/upload` | Upload a PDF / DOCX / XLSX (≤ 20 MB) |
| `GET` | `/domains/documents/files` | Documents uploaded since the app started |
| `DELETE` | `/domains/documents/files/{doc_id}` | Remove a document from the list |
| `POST` | `/debug/cypher` | Run an arbitrary Cypher query — disabled unless `DEBUG_API_TOKEN` is set; requires `Authorization: Bearer <token>` |

## Running tests

```bash
pip install -r requirements.txt
pytest                      # unit + API tests, integration tests deselected
```

`pytest.ini` enforces 100% coverage over `src/` and `plugins/`. Tests marked `integration` are
excluded by default and are currently placeholders that require live Neo4j and Postgres.

## Project structure

```
src/
  main.py            FastAPI app and startup wiring (indexes, domains, LLMs, pipeline)
  config.py          Settings (env / .env)
  api/routes.py      HTTP endpoints
  models/core.py     RawEntity, MetadataChunk, SearchResult, ParsedIntent, SearchState
  domain/            Plugin interfaces: DomainConfig, registry, graph schema, breadcrumb, intent prompt
  connectors/        XML file connector, file-system / upload connector (PDF, DOCX, XLSX)
  ingestion/         Ingestion orchestrator and breadcrumb generator
  indexers/          pgvector, Whoosh ("lucene"), and Neo4j writers
  search/            Per-index searchers and the LangGraph SearchOrchestrator
  aggregation/       RRF and graph-boost post-processors
  llm/               LLM client interface, Anthropic and Ollama clients, intent parser, synthesizer
plugins/
  metadata/          Financial planning metadata domain
  documents/         Uploaded-document domain
data/                Sample metadata XML; upload and Whoosh index directories
docs/                Full framework design (01–08) and Phase 1 MVP design (docs/mvp/)
tests/               Unit, API, and (placeholder) integration tests
```

The design documents in [`docs/`](docs/) describe the broader framework vision; some options there
(for example a FAISS vector backend and an LLM-as-judge evaluator) are **not** part of the current
implementation. [`docs/mvp/`](docs/mvp/) describes what is built.

## Limitations

Known gaps in the current MVP:

- `search_mode` is accepted by `/search` but not yet applied — every query runs all three indexes.
- The metadata index endpoint always re-indexes the configured `METADATA_FILE`; the
  `metadata_file` / `metadata_xml` request fields are not yet used.
- The uploaded-document list is in memory, and `DELETE /domains/documents/files/{doc_id}` does
  not yet remove that document's chunks from the indexes.
- Keyword-index terms are named "lucene" in code; the implementation is Whoosh.
- There is no authentication on the search and indexing endpoints, and LLM-generated Cypher hints
  are executed against Neo4j — run only in a trusted, local environment. `/debug/cypher` is
  disabled by default and token-protected when enabled.
- Default credentials in `docker-compose.yml` are for local development only.

## Roadmap

From [`docs/mvp/README.md`](docs/mvp/README.md), deferred beyond Phase 1:

- Additional domains (HR / org, compliance) and multi-domain routing
- Background job queue for large files and scheduled incremental indexing
- LLM-based evaluation (LLM-as-judge)
- CDC / event-stream ingestion, Elasticsearch as a keyword backend, cross-domain graph linking

## License

No license file is included in this repository yet; all rights reserved by the author unless a
license is added.
