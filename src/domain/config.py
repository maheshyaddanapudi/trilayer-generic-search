from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.domain.breadcrumb import BreadcrumbTemplate
from src.domain.connector import SourceConnector
from src.domain.entity_types import EntityTypeRegistry
from src.domain.graph_schema import GraphSchema
from src.domain.intent_prompt import IntentPromptConfig


class TriggerMode(str, Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    EVENT = "event"


@dataclass
class TriggerConfig:
    mode: TriggerMode = TriggerMode.MANUAL
    full_reindex_on_startup: bool = False


@dataclass
class DomainConfig:
    domain_id: str
    display_name: str
    description: str
    connector: SourceConnector
    entity_types: EntityTypeRegistry
    graph_schema: GraphSchema
    breadcrumb_template: BreadcrumbTemplate
    intent_prompt: IntentPromptConfig
    trigger_config: TriggerConfig = field(default_factory=TriggerConfig)
    rrf_k: int = 60
    graph_boost_factor: float = 1.5
    graph_boost_top_n: int = 3
    default_top_k: int = 10
    namespace_isolated: bool = True
