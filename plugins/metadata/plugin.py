from __future__ import annotations

from pathlib import Path

from src.domain.breadcrumb import BreadcrumbSlot, TemplateBreadcrumbTemplate
from src.domain.config import DomainConfig, TriggerConfig, TriggerMode
from src.domain.entity_types import EntityTypeDefinition, EntityTypeRegistry, FieldType, PropertyDefinition
from src.domain.graph_schema import (
    GraphSchema, NodeLabel, RelationshipDefinition, TraversalDirection, TraversalRule,
)
from src.domain.intent_prompt import IntentPromptConfig
from src.connectors.xml_file import XMLFileConnector

# ── Entity Types ─────────────────────────────────────────────────────────────

METADATA_ENTITY_TYPES = EntityTypeRegistry()

METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Account", id_field="code", display_field="code", description_field="desc",
    properties=[
        PropertyDefinition("code", FieldType.STRING, required=True),
        PropertyDefinition("desc", FieldType.STRING, required=True),
        PropertyDefinition("type", FieldType.STRING),
        PropertyDefinition("parent", FieldType.STRING),
        PropertyDefinition("attributes", FieldType.LIST),
    ],
    parent_type="Account",
    searchable_fields=["code", "desc"],
))
METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Level", id_field="code", display_field="code", description_field="desc",
    properties=[PropertyDefinition("code", FieldType.STRING, required=True),
                PropertyDefinition("desc", FieldType.STRING, required=True)],
))
METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Version", id_field="code", display_field="code", description_field="desc",
    properties=[PropertyDefinition("code", FieldType.STRING, required=True),
                PropertyDefinition("desc", FieldType.STRING, required=True),
                PropertyDefinition("start_time", FieldType.DATE),
                PropertyDefinition("end_time", FieldType.DATE)],
))
METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Sheet", id_field="name", display_field="name", description_field="name",
    properties=[PropertyDefinition("name", FieldType.STRING, required=True),
                PropertyDefinition("type", FieldType.STRING)],
))
METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Dimension", id_field="name", display_field="name", description_field="name",
    properties=[PropertyDefinition("name", FieldType.STRING, required=True)],
))
METADATA_ENTITY_TYPES.register(EntityTypeDefinition(
    name="DimValue", id_field="name", display_field="name", description_field="value",
    properties=[PropertyDefinition("name", FieldType.STRING, required=True),
                PropertyDefinition("value", FieldType.STRING, required=True),
                PropertyDefinition("dimension", FieldType.STRING)],
    parent_type="Dimension",
))

# ── Graph Schema ──────────────────────────────────────────────────────────────

METADATA_GRAPH_SCHEMA = GraphSchema(
    domain_namespace="meta",
    node_labels={
        "Account":   NodeLabel("meta_Account",   "Account",   "code",  ["code", "desc"]),
        "Level":     NodeLabel("meta_Level",     "Level",     "code",  ["code", "desc"]),
        "Version":   NodeLabel("meta_Version",   "Version",   "code",  ["code", "desc"]),
        "Sheet":     NodeLabel("meta_Sheet",     "Sheet",     "name",  ["name"]),
        "Dimension": NodeLabel("meta_Dimension", "Dimension", "name",  ["name"]),
        "DimValue":  NodeLabel("meta_DimValue",  "DimValue",  "name",  ["name", "value"]),
    },
    relationships=[
        RelationshipDefinition("PARENT_OF",        "meta_Account",   "meta_Account",   directed=True,  inverse_name="CHILD_OF"),
        RelationshipDefinition("LINKED_TO",        "meta_Account",   "meta_Account",   directed=False),
        RelationshipDefinition("INCLUDES_ACCOUNT", "meta_Sheet",     "meta_Account",   directed=True),
        RelationshipDefinition("USES_VERSION",     "meta_Sheet",     "meta_Version",   directed=True),
        RelationshipDefinition("USES_LEVEL",       "meta_Sheet",     "meta_Level",     directed=True),
        RelationshipDefinition("HAS_VALUE",        "meta_Dimension", "meta_DimValue",  directed=True),
    ],
    traversal_rules=[
        TraversalRule("PARENT_OF",        TraversalDirection.OUTBOUND, max_depth=3, use_for_boost=True),
        TraversalRule("LINKED_TO",        TraversalDirection.BOTH,     max_depth=1, use_for_boost=True),
        TraversalRule("INCLUDES_ACCOUNT", TraversalDirection.INBOUND,  max_depth=1, use_for_boost=False),
    ],
    boost_edges=["PARENT_OF", "LINKED_TO"],
)

# ── Breadcrumb Template ───────────────────────────────────────────────────────

METADATA_BREADCRUMB = TemplateBreadcrumbTemplate(
    identity_slot=BreadcrumbSlot(field_path="entity_id"),
    description_slot=BreadcrumbSlot(field_path="description"),
    attribute_slots=[
        BreadcrumbSlot(field_path="properties.type",             label=None),
        BreadcrumbSlot(field_path="properties.metric",           label="metric="),
        BreadcrumbSlot(field_path="properties.billing_type",     label="billing="),
        BreadcrumbSlot(field_path="properties.formula",          label="formula="),
        BreadcrumbSlot(field_path="properties.start_time",       label="from:"),
        BreadcrumbSlot(field_path="properties.end_time",         label="to:"),
        # Hierarchy / link info — only populated for Account entities by the
        # XML connector. Surfaces "parent=…", "children=…", "linked=…" so the
        # embedding (and the LLM synthesizer) sees the immediate neighbourhood
        # without a follow-up graph query.
        BreadcrumbSlot(field_path="properties.parent_code",      label="parent="),
        BreadcrumbSlot(field_path="properties.children",         label="children="),
        BreadcrumbSlot(field_path="properties.linked_accounts",  label="linked="),
    ],
    lineage_depth=2,
    separator=" | ",
    max_total_length=512,
)

# ── Intent Prompt ─────────────────────────────────────────────────────────────

METADATA_INTENT_PROMPT = IntentPromptConfig(
    entity_type_descriptions={
        "Account":   "financial accounts like REVENUE, COGS, SAAS_REVENUE, NET_INCOME, OPEX",
        "Level":     "aggregation granularity: CORPORATE, DIVISION, DEPARTMENT",
        "Version":   "planning scenarios: ACTUAL, BUDGET, Q2_FORECAST",
        "Sheet":     "planning sheets: PL_Summary, Revenue_Detail, COGS_Detail",
        "Dimension": "analytical dimensions: Region, Product, Department",
        "DimValue":  "dimension members: NA, EMEA, APAC, ENTERPRISE, SMB",
    },
    synonym_expansion_map={
        "revenue":   ["arr", "mrr", "income", "sales", "REVENUE", "PROD_REVENUE"],
        "cost":      ["cogs", "expense", "COGS", "OPEX", "DIRECT_MATERIAL"],
        "profit":    ["gross profit", "net income", "GROSS_PROFIT", "NET_INCOME"],
        "saas":      ["subscription", "arr", "recurring", "SAAS_REVENUE"],
        "budget":    ["plan", "forecast", "BUDGET", "Q2_FORECAST"],
        "actual":    ["realized", "recorded", "ACTUAL"],
    },
    query_type_examples={
        "lookup":    ["show me SAAS_REVENUE", "what is ACTUAL version"],
        "traversal": ["children of REVENUE", "what accounts roll up to OPEX"],
        "discovery": ["recurring revenue accounts", "where is ARR tracked"],
    },
    cypher_hint_patterns={
        "children":       "MATCH (a:meta_Account)-[:PARENT_OF]->(c:meta_Account) WHERE a.code = $code RETURN c",
        "ancestors":      "MATCH (a:meta_Account)-[:PARENT_OF*]->(c:meta_Account) WHERE c.code = $code RETURN a",
        "sheet_accounts": "MATCH (s:meta_Sheet)-[:INCLUDES_ACCOUNT]->(a:meta_Account) WHERE s.name = $name RETURN a",
        "linked":         "MATCH (a:meta_Account)-[:LINKED_TO]-(b:meta_Account) WHERE a.code = $code RETURN b",
    },
    grounding_format_description="Sheet > Version/Level > Account hierarchy path",
)


def build_metadata_domain(metadata_file: Path) -> DomainConfig:
    return DomainConfig(
        domain_id="metadata",
        display_name="Financial Planning Metadata",
        description="Accounts, Versions, Sheets, Levels, and Dimensions from the financial planning system",
        connector=XMLFileConnector(
            file_path=metadata_file,
            entity_types=METADATA_ENTITY_TYPES,
        ),
        entity_types=METADATA_ENTITY_TYPES,
        graph_schema=METADATA_GRAPH_SCHEMA,
        breadcrumb_template=METADATA_BREADCRUMB,
        intent_prompt=METADATA_INTENT_PROMPT,
        trigger_config=TriggerConfig(
            mode=TriggerMode.MANUAL,
            full_reindex_on_startup=True,
        ),
        rrf_k=60,
        graph_boost_factor=1.5,
        graph_boost_top_n=3,
        default_top_k=10,
        namespace_isolated=True,
    )
