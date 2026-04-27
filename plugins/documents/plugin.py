from __future__ import annotations

from pathlib import Path

from src.domain.breadcrumb import BreadcrumbSlot, TemplateBreadcrumbTemplate
from src.domain.config import DomainConfig, TriggerConfig, TriggerMode
from src.domain.entity_types import EntityTypeDefinition, EntityTypeRegistry, FieldType, PropertyDefinition
from src.domain.graph_schema import (
    GraphSchema, NodeLabel, RelationshipDefinition, TraversalDirection, TraversalRule,
)
from src.domain.intent_prompt import IntentPromptConfig
from src.connectors.file_system import FileSystemConnector, SUPPORTED_MIMES

# ── Entity Types ─────────────────────────────────────────────────────────────

DOCUMENT_ENTITY_TYPES = EntityTypeRegistry()

DOCUMENT_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Document", id_field="doc_id", display_field="title", description_field="summary",
    properties=[
        PropertyDefinition("doc_id",         FieldType.STRING, required=True),
        PropertyDefinition("title",          FieldType.STRING, required=True),
        PropertyDefinition("doc_type",       FieldType.STRING),
        PropertyDefinition("status",         FieldType.STRING),
        PropertyDefinition("effective_date", FieldType.DATE),
        PropertyDefinition("owner",          FieldType.STRING),
        PropertyDefinition("version",        FieldType.STRING),
        PropertyDefinition("tags",           FieldType.LIST),
    ],
    searchable_fields=["title", "doc_type", "tags"],
))
DOCUMENT_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Section", id_field="section_id", display_field="heading",
    description_field="content_summary",
    properties=[
        PropertyDefinition("section_id",      FieldType.STRING, required=True),
        PropertyDefinition("doc_id",          FieldType.STRING, required=True),
        PropertyDefinition("heading",         FieldType.STRING, required=True),
        PropertyDefinition("order_index",     FieldType.NUMBER),
        PropertyDefinition("content_summary", FieldType.STRING),
        PropertyDefinition("page_number",     FieldType.NUMBER),
    ],
    parent_type="Document",
    searchable_fields=["heading", "content_summary"],
))

# ── Graph Schema ──────────────────────────────────────────────────────────────

DOCUMENT_GRAPH_SCHEMA = GraphSchema(
    domain_namespace="doc",
    node_labels={
        "Document": NodeLabel("doc_Document", "Document", "doc_id",     ["title", "doc_type"]),
        "Section":  NodeLabel("doc_Section",  "Section",  "section_id", ["heading"]),
    },
    relationships=[
        RelationshipDefinition("HAS_SECTION", "doc_Document", "doc_Section",  directed=True),
        RelationshipDefinition("SUPERSEDES",  "doc_Document", "doc_Document", directed=True, inverse_name="SUPERSEDED_BY"),
        RelationshipDefinition("TAGGED_WITH", "doc_Document", "doc_Tag",      directed=True),
    ],
    traversal_rules=[
        TraversalRule("HAS_SECTION", TraversalDirection.OUTBOUND, max_depth=1, use_for_boost=True),
        TraversalRule("SUPERSEDES",  TraversalDirection.OUTBOUND, max_depth=2, use_for_boost=False),
    ],
    boost_edges=["HAS_SECTION"],
)

# ── Breadcrumb Template ───────────────────────────────────────────────────────

DOCUMENT_BREADCRUMB = TemplateBreadcrumbTemplate(
    identity_slot=BreadcrumbSlot(field_path="name"),
    description_slot=BreadcrumbSlot(field_path="description"),
    attribute_slots=[
        BreadcrumbSlot(field_path="properties.owner",          label="owner="),
        BreadcrumbSlot(field_path="properties.effective_date", label="effective="),
        BreadcrumbSlot(field_path="properties.status",         label=None),
        BreadcrumbSlot(field_path="properties.tags",           label="tags="),
    ],
    lineage_depth=1,
    separator=" | ",
    max_total_length=512,
)

# ── Intent Prompt ─────────────────────────────────────────────────────────────

DOCUMENT_INTENT_PROMPT = IntentPromptConfig(
    entity_type_descriptions={
        "Document": "policy documents, SOPs, guides, procedures",
        "Section":  "sections within documents — e.g. §4.2 Approval Thresholds",
    },
    synonym_expansion_map={
        "approval":   ["sign-off", "authorization", "delegation"],
        "expense":    ["expenditure", "cost", "spend", "reimbursement"],
        "vendor":     ["supplier", "contractor", "third-party", "procurement"],
        "policy":     ["procedure", "guideline", "SOP", "standard"],
        "capital":    ["capex", "investment", "asset"],
        "travel":     ["T&E", "trip", "accommodation", "airfare"],
        "onboarding": ["setup", "registration", "enrollment"],
    },
    query_type_examples={
        "lookup":    ["Capital Expenditure Policy Rev3", "find expense policy"],
        "traversal": ["sections of the CapEx policy", "what's in the expense guide"],
        "discovery": ["how do I get approval for large purchases",
                      "travel reimbursement limits"],
    },
    cypher_hint_patterns={
        "sections":   "MATCH (d:doc_Document)-[:HAS_SECTION]->(s:doc_Section) WHERE d.title CONTAINS $title RETURN s",
        "supersedes": "MATCH (d:doc_Document)-[:SUPERSEDES*]->(old:doc_Document) WHERE d.doc_id = $id RETURN old",
    },
    grounding_format_description="Document Title > §Section heading (owner, effective date)",
)


def build_document_domain(uploads_dir: Path) -> DomainConfig:
    return DomainConfig(
        domain_id="documents",
        display_name="Policy and Procedure Documents",
        description="Uploaded PDF, DOCX, and XLSX documents — policies, SOPs, guides",
        connector=FileSystemConnector(
            watch_dir=uploads_dir,
            supported_mimes=list(SUPPORTED_MIMES),
        ),
        entity_types=DOCUMENT_ENTITY_TYPES,
        graph_schema=DOCUMENT_GRAPH_SCHEMA,
        breadcrumb_template=DOCUMENT_BREADCRUMB,
        intent_prompt=DOCUMENT_INTENT_PROMPT,
        trigger_config=TriggerConfig(
            mode=TriggerMode.MANUAL,
            full_reindex_on_startup=False,
        ),
        rrf_k=60,
        graph_boost_factor=1.4,
        graph_boost_top_n=3,
        default_top_k=10,
        namespace_isolated=True,
    )
