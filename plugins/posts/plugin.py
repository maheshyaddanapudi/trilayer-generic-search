"""Posts domain plugin — JSON API (jsonplaceholder /posts).

Registers a domain that ingests blog posts from a REST API.
Each Post is a searchable entity; posts are grouped under User parent nodes
so hierarchy traversal ("show me all posts by user 3") works out of the box.
"""
from __future__ import annotations

from src.domain.breadcrumb import BreadcrumbSlot, TemplateBreadcrumbTemplate
from src.domain.config import DomainConfig, TriggerConfig, TriggerMode
from src.domain.entity_types import (
    EntityTypeDefinition, EntityTypeRegistry, FieldType, PropertyDefinition,
)
from src.domain.graph_schema import (
    GraphSchema, NodeLabel, RelationshipDefinition, TraversalDirection, TraversalRule,
)
from src.domain.intent_prompt import IntentPromptConfig
from src.connectors.json_api import JsonApiConnector

# ── Entity Types ──────────────────────────────────────────────────────────────

POSTS_ENTITY_TYPES = EntityTypeRegistry()

POSTS_ENTITY_TYPES.register(EntityTypeDefinition(
    name="Post",
    id_field="post_id",
    display_field="title",
    description_field="body",
    properties=[
        PropertyDefinition("post_id", FieldType.STRING, required=True),
        PropertyDefinition("user_id", FieldType.STRING),
        PropertyDefinition("title",   FieldType.STRING, required=True),
        PropertyDefinition("body",    FieldType.STRING),
    ],
    parent_type="User",
    searchable_fields=["title", "body"],
))

# ── Graph Schema ──────────────────────────────────────────────────────────────
#
# Graph layout:
#
#   (posts_User {user_id}) -[:AUTHORED]-> (posts_Post {post_id})
#
# This lets us answer: "show all posts by user 3" via graph traversal.

POSTS_GRAPH_SCHEMA = GraphSchema(
    domain_id="posts",
    node_labels=[
        NodeLabel(entity_type="Post",  label="posts_Post",  id_property="post_id"),
        NodeLabel(entity_type="User",  label="posts_User",  id_property="user_id"),
    ],
    relationships=[
        RelationshipDefinition(
            from_entity_type = "User",
            to_entity_type   = "Post",
            relationship_type = "AUTHORED",
            from_id_property  = "user_id",
            to_id_property    = "post_id",
        ),
    ],
    traversal_rules=[
        TraversalRule(
            start_entity_type  = "User",
            relationship_type  = "AUTHORED",
            direction          = TraversalDirection.OUTBOUND,
            end_entity_type    = "Post",
        ),
    ],
)

# ── Breadcrumb Template ───────────────────────────────────────────────────────
#
# Produces strings like:
#   "sunt aut facere... | Post | parent:user_1 | quia et suscipit... | user_id=1"
#
# The description slot carries the post body so semantic search finds posts by
# their content, not just their title.

POSTS_BREADCRUMB = TemplateBreadcrumbTemplate(
    identity_slot    = BreadcrumbSlot(field_path="name"),             # title
    description_slot = BreadcrumbSlot(field_path="description"),      # body text
    attribute_slots  = [
        BreadcrumbSlot(field_path="properties.user_id", label="user_id="),
        BreadcrumbSlot(field_path="properties.post_id", label="post_id="),
    ],
    lineage_depth   = 1,   # one level up: User
    separator       = " | ",
    max_total_length = 512,
)

# ── Intent Prompt Config ──────────────────────────────────────────────────────
#
# Tells the LLM what entity types exist, example queries, and the Cypher
# patterns to use when generating hints.

POSTS_INTENT_PROMPT = IntentPromptConfig(
    entity_type_descriptions={
        "Post": "blog posts with a title and body text, authored by a user",
        "User": "authors identified by user_id (1–10)",
    },
    synonym_expansion_map={
        "post":    ["article", "blog", "entry", "write-up"],
        "author":  ["user", "writer", "creator"],
        "find":    ["search", "show", "list", "get"],
    },
    query_type_examples={
        "LOOKUP":    ["find post 42", "what is post id 7"],
        "TRAVERSAL": ["posts by user 3", "all articles from user 1",
                      "what did user 5 write?"],
        "DISCOVERY": ["posts about identity", "articles mentioning architecture",
                      "find posts about error handling"],
    },
    cypher_hint_patterns={
        "posts_by_user": (
            "MATCH (u:posts_User {user_id: $user_id})-[:AUTHORED]->(p:posts_Post) "
            "RETURN p.chunk_id AS chunk_id, p.breadcrumb AS breadcrumb"
        ),
        "post_by_id": (
            "MATCH (p:posts_Post {post_id: $post_id}) "
            "RETURN p.chunk_id AS chunk_id, p.breadcrumb AS breadcrumb"
        ),
    },
)

# ── Domain Factory ────────────────────────────────────────────────────────────

def build_posts_domain() -> DomainConfig:
    """Return the fully wired DomainConfig for the posts domain.

    Call this once in src/main.py:
        registry.register(build_posts_domain())
    """
    return DomainConfig(
        domain_id      = "posts",
        display_name   = "Blog Posts (JSONPlaceholder)",
        connector      = JsonApiConnector(
            base_url  = "https://jsonplaceholder.typicode.com/posts",
            domain_id = "posts",
        ),
        entity_types       = POSTS_ENTITY_TYPES,
        graph_schema       = POSTS_GRAPH_SCHEMA,
        breadcrumb_template = POSTS_BREADCRUMB,
        intent_prompt      = POSTS_INTENT_PROMPT,
        trigger_config     = TriggerConfig(
            mode                   = TriggerMode.MANUAL,
            full_reindex_on_startup = True,   # fetch and index on every restart
        ),
        rrf_k              = 60,
        graph_boost_factor  = 1.5,
        graph_boost_top_n   = 3,
        default_top_k       = 10,
        namespace_isolated  = True,
    )
