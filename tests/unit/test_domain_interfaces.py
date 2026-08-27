from __future__ import annotations

import pytest

from src.aggregation.base import AggregationPipeline, ResultPostProcessor
from src.domain.breadcrumb import BreadcrumbContext, BreadcrumbSlot, TemplateBreadcrumbTemplate, _resolve
from src.domain.config import DomainConfig, TriggerConfig, TriggerMode
from src.domain.connector import SourceConnector
from src.domain.entity_types import EntityTypeDefinition, EntityTypeRegistry, FieldType, PropertyDefinition
from src.domain.graph_schema import (
    GraphSchema, NodeLabel, RelationshipDefinition, TraversalDirection, TraversalRule,
)
from src.domain.intent_prompt import IntentPromptConfig
from src.domain.registry import DomainRegistry
from src.models.core import SearchResult


# ── EntityTypeRegistry ────────────────────────────────────────────────────────

def test_entity_type_registry_register_and_get():
    reg = EntityTypeRegistry()
    defn = EntityTypeDefinition(name="Account", id_field="code",
                                display_field="code", description_field="desc")
    reg.register(defn)
    assert reg.get("Account") is defn


def test_entity_type_registry_contains():
    reg = EntityTypeRegistry()
    reg.register(EntityTypeDefinition("X", "id", "id", "desc"))
    assert "X" in reg
    assert "Y" not in reg


def test_entity_type_registry_all_and_names():
    reg = EntityTypeRegistry()
    reg.register(EntityTypeDefinition("A", "id", "id", "desc"))
    reg.register(EntityTypeDefinition("B", "id", "id", "desc"))
    assert set(reg.names()) == {"A", "B"}
    assert len(reg.all()) == 2


def test_entity_type_registry_get_missing():
    reg = EntityTypeRegistry()
    with pytest.raises(KeyError):
        reg.get("Missing")


def test_property_definition_defaults():
    p = PropertyDefinition("code", FieldType.STRING)
    assert p.required is False


# ── GraphSchema ───────────────────────────────────────────────────────────────

def test_graph_schema_node_label_for():
    schema = GraphSchema(
        domain_namespace="meta",
        node_labels={"Account": NodeLabel("meta_Account", "Account", "code")},
    )
    assert schema.node_label_for("Account") == "meta_Account"


def test_graph_schema_boost_edges():
    schema = GraphSchema(domain_namespace="meta", boost_edges=["PARENT_OF"])
    assert schema.boost_relation_types() == ["PARENT_OF"]


def test_traversal_rule_defaults():
    rule = TraversalRule("PARENT_OF", TraversalDirection.OUTBOUND)
    assert rule.max_depth == 1
    assert rule.use_for_boost is False


# ── BreadcrumbTemplate ────────────────────────────────────────────────────────

def _make_template(max_length=512):
    return TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot(field_path="entity_id"),
        description_slot=BreadcrumbSlot(field_path="description"),
        attribute_slots=[
            BreadcrumbSlot(field_path="properties.type", label=None),
            BreadcrumbSlot(field_path="properties.metric", label="metric="),
        ],
        lineage_depth=2,
        separator=" | ",
        max_total_length=max_length,
    )


def test_breadcrumb_no_lineage():
    tmpl = _make_template()
    ctx = BreadcrumbContext(lineage=[], domain_display="Metadata")
    result = tmpl.generate("REVENUE", "Account", "REVENUE", "Total Revenue",
                           {"type": "standard"}, ctx)
    assert "REVENUE" in result
    assert "Account" in result
    assert "Metadata" in result
    assert "Total Revenue" in result
    assert "standard" in result


def test_breadcrumb_with_lineage():
    tmpl = _make_template()
    ctx = BreadcrumbContext(lineage=["REVENUE"])
    result = tmpl.generate("PROD_REVENUE", "Account", "PROD_REVENUE", "Product Revenue",
                           {"type": "standard"}, ctx)
    assert "parent:REVENUE" in result


def test_breadcrumb_with_deep_lineage():
    tmpl = _make_template()
    ctx = BreadcrumbContext(lineage=["PROD_REVENUE", "REVENUE"])
    result = tmpl.generate("SAAS_REVENUE", "Account", "SAAS_REVENUE", "SaaS",
                           {}, ctx)
    assert "parent:PROD_REVENUE > REVENUE" in result


def test_breadcrumb_attribute_with_label():
    tmpl = _make_template()
    ctx = BreadcrumbContext(lineage=[])
    result = tmpl.generate("SAAS_REVENUE", "Account", "SAAS_REVENUE", "desc",
                           {"metric": "arr"}, ctx)
    assert "metric=arr" in result


def test_breadcrumb_attribute_list():
    tmpl = TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot("entity_id"),
        description_slot=BreadcrumbSlot("description"),
        attribute_slots=[BreadcrumbSlot("properties.tags", label="tags=")],
        separator=" | ",
    )
    ctx = BreadcrumbContext()
    result = tmpl.generate("DOC1", "Document", "DOC1", "desc", {"tags": ["a", "b"]}, ctx)
    assert "tags=a, b" in result


def test_breadcrumb_truncation():
    tmpl = _make_template(max_length=30)
    ctx = BreadcrumbContext(lineage=[])
    result = tmpl.generate("E", "T", "E", "A very long description that will be cut", {}, ctx)
    assert len(result) <= 30


def test_breadcrumb_missing_property_skipped():
    tmpl = _make_template()
    ctx = BreadcrumbContext()
    result = tmpl.generate("X", "Account", "X", "desc", {}, ctx)
    assert "metric=" not in result


def test_breadcrumb_name_slot():
    tmpl = TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot("name"),
        description_slot=BreadcrumbSlot("description"),
        attribute_slots=[],
        separator=" | ",
    )
    ctx = BreadcrumbContext()
    result = tmpl.generate("id1", "Document", "My Doc", "summary", {}, ctx)
    assert result.startswith("My Doc")


# ── IntentPromptConfig ────────────────────────────────────────────────────────

def test_intent_prompt_build_system_prompt():
    cfg = IntentPromptConfig(
        entity_type_descriptions={"Account": "financial accounts"},
        synonym_expansion_map={"revenue": ["arr"]},
        query_type_examples={"lookup": ["SAAS_REVENUE"]},
    )
    prompt = cfg.build_system_prompt()
    assert "Account" in prompt
    assert "revenue" in prompt
    assert "lookup" in prompt
    assert "LOOKUP" in prompt


# ── DomainRegistry ────────────────────────────────────────────────────────────

def test_registry_singleton():
    r1 = DomainRegistry.get_instance()
    r2 = DomainRegistry.get_instance()
    assert r1 is r2


def test_registry_reset():
    r1 = DomainRegistry.get_instance()
    DomainRegistry.reset()
    r2 = DomainRegistry.get_instance()
    assert r1 is not r2


def test_registry_get_missing():
    reg = DomainRegistry()
    with pytest.raises(KeyError) as exc_info:
        reg.get("nonexistent")
    assert "nonexistent" in str(exc_info.value)


def test_registry_contains():
    from unittest.mock import MagicMock
    reg = DomainRegistry()
    cfg = MagicMock()
    cfg.domain_id = "metadata"
    reg.register(cfg)
    assert "metadata" in reg
    assert "other" not in reg


def test_registry_all_and_ids():
    from unittest.mock import MagicMock
    reg = DomainRegistry()
    for did in ("metadata", "documents"):
        cfg = MagicMock()
        cfg.domain_id = did
        reg.register(cfg)
    assert set(reg.ids()) == {"metadata", "documents"}
    assert len(reg.all()) == 2


# ── TriggerConfig ─────────────────────────────────────────────────────────────

def test_trigger_config_defaults():
    tc = TriggerConfig()
    assert tc.mode == TriggerMode.MANUAL
    assert tc.full_reindex_on_startup is False


# ── AggregationPipeline with stages (covers base.py:21) ──────────────────────

def _sr(cid, score=1.0, source="vector"):
    return SearchResult(
        chunk_id=cid, score=score, breadcrumb=f"BC {cid}",
        entity_id=cid, entity_type="Account", domain_id="metadata",
        rank=0, source=source,
    )


def test_aggregation_pipeline_with_nonempty_stages():
    class PassThrough(ResultPostProcessor):
        def process(self, results, **kwargs):
            return results

    pipeline = AggregationPipeline([PassThrough()])
    results = [_sr("c1"), _sr("c2")]
    out = pipeline.run(results, top_k=5)
    assert len(out) == 2


# ── BreadcrumbTemplate — uncovered branches ───────────────────────────────────

def test_resolve_non_dict_intermediate():
    # L33: _resolve returns None when intermediate is not a dict
    result = _resolve("properties.x.deep", {"x": "string_value"})
    assert result is None


def test_resolve_slot_custom_path_resolves():
    # L98: else branch + L101 + L104 (no label)
    tmpl = TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot(field_path="properties.custom_id"),
        description_slot=BreadcrumbSlot(field_path="description"),
        attribute_slots=[],
        lineage_depth=0,
    )
    ctx = BreadcrumbContext(lineage=[], domain_display="Test")
    result = tmpl.generate("E1", "Type", "Name", "Desc", {"custom_id": "CUSTOM"}, ctx)
    assert "CUSTOM" in result


def test_resolve_slot_custom_path_missing():
    # L98: else branch → _resolve returns None → L100 returns None → fallback to entity_id
    tmpl = TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot(field_path="properties.nonexistent"),
        description_slot=BreadcrumbSlot(field_path="description"),
        attribute_slots=[],
        lineage_depth=0,
    )
    ctx = BreadcrumbContext(lineage=[], domain_display="Test")
    result = tmpl.generate("E1", "Type", "Name", "Desc", {}, ctx)
    assert "E1" in result  # falls back to entity_id


def test_resolve_slot_with_label():
    # L103: slot.label is non-None → returns labeled string
    tmpl = TemplateBreadcrumbTemplate(
        identity_slot=BreadcrumbSlot(field_path="entity_id", label="id="),
        description_slot=BreadcrumbSlot(field_path="description"),
        attribute_slots=[],
        lineage_depth=0,
    )
    ctx = BreadcrumbContext(lineage=[], domain_display="Test")
    result = tmpl.generate("REVENUE", "Account", "REVENUE", "desc", {}, ctx)
    assert "id=REVENUE" in result


# ── SourceConnector.fetch_since (covers connector.py:23) ─────────────────────

def test_connector_fetch_since_raises():
    class MinimalConnector(SourceConnector):
        def connect(self): pass
        def disconnect(self): pass
        def fetch_all(self): return iter([])

    conn = MinimalConnector()
    with pytest.raises(NotImplementedError):
        next(conn.fetch_since(None))  # type: ignore[arg-type]
