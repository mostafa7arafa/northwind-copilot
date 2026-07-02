"""Centralised configuration for the Northwind Copilot agent.

All tunable values — model names, file paths, and agent parameters — live here
so the rest of the codebase never hard-codes them. Values can be overridden via
environment variables (loaded from a local ``.env`` file).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env once, at import time, before any setting is read.
load_dotenv()


def _env(name: str, default: str) -> str:
    """Return an environment variable, falling back to a default.

    Args:
        name: The environment variable name.
        default: The value to use when the variable is unset or empty.

    Returns:
        The resolved string value.
    """
    value = os.getenv(name)
    if value is None:
        return default
    # Some env loaders (e.g. langgraph dev reading .env) pass values with the
    # surrounding quotes attached; strip those and whitespace before use.
    value = value.strip().strip("\"'").strip()
    return value if value else default


@dataclass(frozen=True)
class Settings:
    """Immutable application settings.

    Attributes:
        primary_model: Ollama model name used as the local-first primary.
        fallback_model: OpenAI model name used when the primary fails.
        embedding_model: OpenAI embedding model used for document retrieval.
        temperature: Sampling temperature; 0 for deterministic SQL.
        database_uri: SQLAlchemy URI for the Northwind database.
        sample_rows_in_table_info: Sample rows included in schema dumps; 0 keeps
            the re-sent schema payload small.
        docs_dir: Directory of markdown knowledge documents.
        faiss_path: On-disk location of the FAISS index.
        max_context_tokens: Token budget for the trimmed conversation window on
            local (Ollama) engines, whose context windows are tight.
        max_context_tokens_cloud: Larger budget for cloud engines, so a curated
            multi-turn history survives the trim step.
    """

    primary_model: str = _env("PRIMARY_MODEL", "gemma4-12b")
    fallback_model: str = _env("FALLBACK_MODEL", "gpt-4.1-mini")
    embedding_model: str = _env("EMBEDDING_MODEL", "text-embedding-3-small")
    temperature: float = 0.0
    # NB: NOT "DATABASE_URI" — langgraph reserves that name for its own
    # persistence layer and overwrites it with ":memory:" under `langgraph dev`.
    database_uri: str = _env(
        "NORTHWIND_DATABASE_URI", "sqlite:///data/northwind.sqlite"
    )
    sample_rows_in_table_info: int = 0
    docs_dir: str = _env("DOCS_DIR", "docs")
    faiss_path: str = _env("FAISS_PATH", ".faiss_index")
    max_context_tokens: int = 8000
    max_context_tokens_cloud: int = 32000


settings = Settings()
"""Module-level singleton holding the resolved settings."""
