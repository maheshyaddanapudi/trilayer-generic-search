from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # LLM — provider switch
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"

    # LLM — Anthropic
    anthropic_api_key: str = "sk-ant-placeholder"
    intent_model: str = "claude-haiku-4-5-20251001"
    synthesis_model: str = "claude-sonnet-4-6"

    # LLM — Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_intent_model: str = "gemma4:31b"
    ollama_synthesis_model: str = "gemma4:31b"
    ollama_request_timeout_s: float = 180.0

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # PGVector
    postgres_url: str = "postgresql://tgs:tgs_password@localhost:5432/tgs_db"
    postgres_vector_table: str = "metadata_chunks"

    # Whoosh
    whoosh_index_dir: str = "./data/whoosh"

    # Ingestion
    metadata_file: str = "./data/sample_metadata.xml"
    uploads_dir: str = "./data/uploads"
    max_upload_size_mb: int = 20
    default_batch_size: int = 100
    max_breadcrumb_length: int = 512

    # Aggregation
    rrf_k: int = 60
    graph_boost_factor: float = 1.5
    graph_boost_top_n: int = 3

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
