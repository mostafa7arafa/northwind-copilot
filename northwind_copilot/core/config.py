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


def _env_int(name: str, default: int) -> int:
    """Return an integer environment variable, falling back to a default."""
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


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
        ollama_base_url: Base URL of the Ollama daemon. Configurable so the
            service works in Docker (``http://ollama:11434``) as well as locally.
        cors_allow_origins: Comma-separated list of browser origins allowed to
            call the API. Defaults to the local Next.js dev server.
        auth_token: Optional shared bearer token. When set, every API request
            must carry ``Authorization: Bearer <token>``; when empty, the API is
            open (single-user local POC).
        max_messages: Cap on conversation-history length accepted per request.
        max_message_chars: Cap on the size of a single message's content.
        max_preferences_chars: Cap on stored analyst-preferences text.
        rate_limit_per_minute: Max ``/api/chat`` requests per client per minute.
        turn_deadline_seconds: Wall-clock budget for one local analyst turn
            before it is aborted (a stuck small model should be cut promptly).
        turn_deadline_seconds_cloud: Larger budget for cloud engines, whose
            multi-query, multi-chart turns legitimately run longer. The SSE
            heartbeat keeps the connection warm throughout.
        query_timeout_seconds: Wall-clock budget for a single result SQL run.
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

    # --- Web service / deployment -----------------------------------------
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://localhost:11434")
    cors_allow_origins: str = _env(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    auth_token: str = _env("APP_AUTH_TOKEN", "")

    # --- Abuse / cost guards ----------------------------------------------
    max_messages: int = _env_int("MAX_MESSAGES", 40)
    max_message_chars: int = _env_int("MAX_MESSAGE_CHARS", 8000)
    max_preferences_chars: int = _env_int("MAX_PREFERENCES_CHARS", 4000)
    rate_limit_per_minute: int = _env_int("RATE_LIMIT_PER_MINUTE", 20)
    turn_deadline_seconds: int = _env_int("TURN_DEADLINE_SECONDS", 120)
    turn_deadline_seconds_cloud: int = _env_int("TURN_DEADLINE_SECONDS_CLOUD", 300)
    query_timeout_seconds: int = _env_int("QUERY_TIMEOUT_SECONDS", 10)

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse ``cors_allow_origins`` into a list of trimmed origins."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


settings = Settings()
"""Module-level singleton holding the resolved settings."""
