from __future__ import annotations

from abc import ABC, abstractmethod

from src.models.core import SearchResult


class ResultPostProcessor(ABC):
    @abstractmethod
    def process(self, results: list[SearchResult], **kwargs) -> list[SearchResult]: ...


class AggregationPipeline:
    def __init__(self, stages: list[ResultPostProcessor]) -> None:
        self._stages = stages

    def run(self, results: list[SearchResult], top_k: int = 10,
            **kwargs) -> list[SearchResult]:
        current = results
        for stage in self._stages:
            current = stage.process(current, top_k=top_k, **kwargs)
        return current[:top_k]
