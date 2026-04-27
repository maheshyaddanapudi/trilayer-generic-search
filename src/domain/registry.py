from __future__ import annotations

from src.domain.config import DomainConfig

_registry: DomainRegistry | None = None


class DomainRegistry:
    def __init__(self) -> None:
        self._domains: dict[str, DomainConfig] = {}

    def register(self, config: DomainConfig) -> None:
        self._domains[config.domain_id] = config

    def get(self, domain_id: str) -> DomainConfig:
        if domain_id not in self._domains:
            raise KeyError(f"Domain '{domain_id}' not registered. "
                           f"Available: {list(self._domains)}")
        return self._domains[domain_id]

    def all(self) -> list[DomainConfig]:
        return list(self._domains.values())

    def ids(self) -> list[str]:
        return list(self._domains.keys())

    def __contains__(self, domain_id: str) -> bool:
        return domain_id in self._domains

    @staticmethod
    def get_instance() -> DomainRegistry:
        global _registry
        if _registry is None:
            _registry = DomainRegistry()
        return _registry

    @staticmethod
    def reset() -> None:
        global _registry
        _registry = None
