from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.aggregation.base import AggregationPipeline
from src.aggregation.graph_boost import GraphBoostingAggregator
from src.aggregation.rrf import RRFAggregator
from src.api.routes import health_router, index_router, search_router
from src.config import get_settings
from src.domain.registry import DomainRegistry
from src.indexers.graph import GraphIndexWriter
from src.indexers.lucene import LuceneIndexWriter
from src.indexers.vector import VectorIndexWriter
from src.ingestion.breadcrumb_gen import BreadcrumbGenerator
from src.ingestion.orchestrator import IngestionOrchestrator
from src.llm.factory import build_llm_client
from src.llm.intent_parser import IntentParser
from src.llm.synthesizer import Synthesizer
from src.models.core import IngestionMode
from src.search.graph_search import GraphSearch
from src.search.lucene_search import LuceneSearch
from src.search.orchestrator import SearchOrchestrator
from src.search.vector_search import VectorSearch

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── Quiet noisy third-party loggers ───────────────────────────────────────────
# The Neo4j Python driver re-emits server-side ``GqlStatusObject`` notifications
# (``01N50`` label-not-exists, ``01N51`` rel-type-not-exists, ``01N52``
# property-not-exists) at WARNING level on every query that references a
# label / relationship type / property the catalog has not seen yet. During
# bootstrap (and during every cold-cache search) these flood the log with
# thousands of false positives. Pin the logger to ERROR so only real failures
# surface. Anyone debugging the schema can re-enable it locally with
# ``logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)``.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Anonymous Hugging Face Hub downloads emit a one-shot "set HF_TOKEN" warning
# at startup. It's purely informational; demote it.
logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
try:  # best-effort: optional helper, not present in every hf_hub version
    from huggingface_hub.utils import logging as _hf_logging  # type: ignore
    _hf_logging.set_verbosity_error()
except Exception:  # pragma: no cover — defensive
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 1. Graph writer
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        graph_writer = GraphIndexWriter(driver)
    except Exception as exc:
        log.warning("Neo4j unavailable: %s — graph search will return empty results", exc)
        graph_writer = _NullGraphWriter()

    # 2. Vector writer
    from sentence_transformers import SentenceTransformer
    import psycopg2
    model = SentenceTransformer(settings.embedding_model)
    pg_conn = psycopg2.connect(settings.postgres_url)
    vector_writer = VectorIndexWriter(
        conn=pg_conn,
        model=model,
        table=settings.postgres_vector_table,
        dimension=settings.embedding_dimension,
    )

    # 3. Lucene writer
    lucene_writer = LuceneIndexWriter(index_dir=Path(settings.whoosh_index_dir))

    # 4. Register domain plugins
    from plugins.metadata.plugin import build_metadata_domain
    from plugins.documents.plugin import build_document_domain

    registry = DomainRegistry.get_instance()
    registry.register(build_metadata_domain(Path(settings.metadata_file)))
    registry.register(build_document_domain(Path(settings.uploads_dir)))

    # 5. Pre-warm Neo4j catalog so the first query against each label /
    # property does not emit a ``GqlStatusObject`` WARNING. Issued once per
    # registered domain. Idempotent: safe across restarts.
    for _domain_id in registry.ids():
        try:
            graph_writer.bootstrap_schema(registry.get(_domain_id).graph_schema, _domain_id)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("bootstrap_schema for %s failed: %s", _domain_id, exc)

    # 6. Ingestion
    breadcrumb_gen = BreadcrumbGenerator(graph_writer)
    ingest_orch = IngestionOrchestrator(registry, vector_writer, lucene_writer, graph_writer, breadcrumb_gen)
    await _run_sync(ingest_orch.ingest_domain, "metadata", IngestionMode.FULL)

    # 7. LLM + search pipeline
    intent_llm = build_llm_client(settings, role="intent")
    synthesis_llm = build_llm_client(settings, role="synthesis")
    intent_configs = {did: registry.get(did).intent_prompt for did in registry.ids()}
    intent_parser = IntentParser(intent_llm, intent_configs)
    synthesizer = Synthesizer(synthesis_llm)

    agg_pipeline = AggregationPipeline([
        RRFAggregator(k=settings.rrf_k),
        GraphBoostingAggregator(graph_writer, boost_factor=settings.graph_boost_factor,
                                top_n=settings.graph_boost_top_n),
    ])

    search_orch = SearchOrchestrator(
        vector_search=VectorSearch(vector_writer, model),
        lucene_search=LuceneSearch(lucene_writer),
        graph_search=GraphSearch(graph_writer, domain_ids=list(registry.ids())),
        intent_parser=intent_parser,
        synthesizer=synthesizer,
        aggregation_pipeline=agg_pipeline,
        domain_registry=registry,
    )

    # Store on app state
    app.state.graph_writer = graph_writer
    app.state.vector_writer = vector_writer
    app.state.lucene_writer = lucene_writer
    app.state.registry = registry
    app.state.breadcrumb_gen = breadcrumb_gen
    app.state.ingest_orchestrator = ingest_orch
    app.state.search_orchestrator = search_orch
    app.state.indexed_docs = {}

    log.info("TGS MVP startup complete")
    yield

    # Teardown
    pg_conn.close()
    if hasattr(graph_writer, 'close'):
        graph_writer.close()
    DomainRegistry.reset()


async def _run_sync(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


class _NullGraphWriter:
    """Fallback when Neo4j is unavailable."""
    def index(self, chunks): return 0
    def index_entities(self, *a, **kw): return 0
    def index_relationships(self, *a, **kw): return 0
    def get_neighbours(self, *a, **kw): return []
    def get_ancestors(self, *a, **kw): return []
    def get_ancestors_batch(self, *a, **kw): return {}
    def bootstrap_schema(self, *a, **kw): return 0
    def cypher_query(self, *a, **kw): return []
    def close(self): pass

    @property
    def is_ready(self): return False


def create_app() -> FastAPI:
    app = FastAPI(title="Trilayer Generic Search — MVP", version="1.0.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(index_router)
    return app


app = create_app()
