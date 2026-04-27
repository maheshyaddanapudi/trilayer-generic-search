from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langgraph.graph import StateGraph

from src.aggregation.base import AggregationPipeline
from src.aggregation.graph_boost import GraphBoostingAggregator
from src.domain.registry import DomainRegistry
from src.llm.intent_parser import IntentParser
from src.llm.synthesizer import Synthesizer
from src.models.core import ParsedIntent, SearchResult, SearchState
from src.search.graph_search import GraphSearch
from src.search.lucene_search import LuceneSearch
from src.search.vector_search import VectorSearch

log = logging.getLogger(__name__)


class SearchOrchestrator:
    def __init__(
        self,
        vector_search: VectorSearch,
        lucene_search: LuceneSearch,
        graph_search: GraphSearch,
        intent_parser: IntentParser,
        synthesizer: Synthesizer,
        aggregation_pipeline: AggregationPipeline,
        domain_registry: DomainRegistry,
    ) -> None:
        self._vector = vector_search
        self._lucene = lucene_search
        self._graph = graph_search
        self._intent_parser = intent_parser
        self._synthesizer = synthesizer
        self._agg = aggregation_pipeline
        self._registry = domain_registry
        self._graph_obj = self._build_graph()

    def _build_graph(self) -> Any:
        sg = StateGraph(SearchState)
        sg.add_node("parse_intent", self._parse_intent_node)
        sg.add_node("triple_search", self._triple_search_node)
        sg.add_node("aggregate", self._aggregate_node)
        sg.add_node("synthesize", self._synthesize_node)
        sg.set_entry_point("parse_intent")
        sg.add_edge("parse_intent", "triple_search")
        sg.add_edge("triple_search", "aggregate")
        sg.add_edge("aggregate", "synthesize")
        sg.set_finish_point("synthesize")
        return sg.compile()

    async def run(self, query: str, domain: str | None = None,
                  top_k: int = 10) -> SearchState:
        t0 = time.monotonic()
        initial: SearchState = {
            "query": query,
            "domain": domain,
            "top_k": top_k,
        }
        state = await self._graph_obj.ainvoke(initial)
        state["latency_ms"] = (time.monotonic() - t0) * 1000
        return state

    # ── LangGraph Nodes ──────────────────────────────────────────────────────

    async def _parse_intent_node(self, state: SearchState) -> SearchState:
        query = state["query"]
        domain = state.get("domain")
        intent = await asyncio.to_thread(self._intent_parser.parse, query, domain)
        return {**state, "intent": intent}

    async def _triple_search_node(self, state: SearchState) -> SearchState:
        intent: ParsedIntent = state["intent"]
        domain = state.get("domain")
        top_k = state.get("top_k", 10)

        v_task = asyncio.to_thread(self._vector.search, intent, top_k, domain)
        l_task = asyncio.to_thread(self._lucene.search, intent, top_k, domain)
        g_task = asyncio.to_thread(self._graph.search, intent, top_k, domain)

        v, l, g = await asyncio.gather(v_task, l_task, g_task, return_exceptions=True)

        vector_results = v if isinstance(v, list) else []
        lucene_results = l if isinstance(l, list) else []
        graph_results = g if isinstance(g, list) else []

        if not isinstance(v, list):
            log.warning("Vector search error: %s", v)
        if not isinstance(l, list):
            log.warning("Lucene search error: %s", l)
        if not isinstance(g, list):
            log.warning("Graph search error: %s", g)

        return {**state,
                "vector_results": vector_results,
                "lucene_results": lucene_results,
                "graph_results": graph_results}

    async def _aggregate_node(self, state: SearchState) -> SearchState:
        all_results = (
            state.get("vector_results", []) +
            state.get("lucene_results", []) +
            state.get("graph_results", [])
        )
        top_k = state.get("top_k", 10)
        domain = state.get("domain")
        boost_factor = 1.5
        if domain:
            try:
                cfg = self._registry.get(domain)
                boost_factor = cfg.graph_boost_factor
            except KeyError:
                pass

        final = await asyncio.to_thread(
            self._agg.run, all_results, top_k,
            lucene_results=state.get("lucene_results", []),
        )
        return {**state, "final_results": final}

    async def _synthesize_node(self, state: SearchState) -> SearchState:
        query = state["query"]
        results = state.get("final_results", [])
        domain = state.get("domain") or "all"
        synthesis = await asyncio.to_thread(
            self._synthesizer.synthesize, query, results, domain
        )
        return {**state, "synthesis": synthesis}
