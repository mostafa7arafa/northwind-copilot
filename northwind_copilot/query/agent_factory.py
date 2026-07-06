"""Build a request-scoped agent for a chosen provider and model.

The static ``northwind_copilot.query.graph.graph`` always uses the
local-first primary with an OpenAI fallback. The web service instead lets the
user pick the engine per request, so we assemble the agent here from an
:class:`EngineConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain.agents import create_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from northwind_copilot.core.config import settings
from northwind_copilot.core.prompts import build_system_prompt
from northwind_copilot.infra.database import build_database
from northwind_copilot.infra.docs_tool import search_docs
from northwind_copilot.query.middleware import (
    EscalateToFallbackMiddleware,
    make_trim_context,
)

Provider = Literal["ollama", "openai", "openrouter"]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Cloud providers get the ECharts instructions; local models are charted by the
# server from their result table instead.
_CLOUD_PROVIDERS = {"openai", "openrouter"}


@dataclass(frozen=True)
class EngineConfig:
    """A resolved choice of inference engine for one request.

    Attributes:
        provider: Which backend serves the model.
        model: The provider-specific model id (e.g. ``gpt-4.1-mini``).
        api_key: The provider API key, when required (cloud providers).
    """

    provider: Provider
    model: str
    api_key: str | None = None

    @property
    def is_local(self) -> bool:
        """Return whether this engine runs on the local machine (Ollama)."""
        return self.provider == "ollama"

    @property
    def supports_charts(self) -> bool:
        """Return whether the model should emit ECharts specs itself."""
        return self.provider in _CLOUD_PROVIDERS


@dataclass(frozen=True)
class DatasetContext:
    """The uploaded dataset one request runs against (hosted mode).

    Kept separate from :class:`EngineConfig` (which is purely about inference)
    so the agent's data source and its model are independent choices.

    Attributes:
        sqlite_path: Filesystem path to the dataset's read-only SQLite file.
        schema_summary: Generated description of the dataset's tables/columns,
            injected into the system prompt in place of the Northwind rules.
        business_context: User-editable domain notes (formulas, definitions)
            appended to the prompt.
        golden_examples: ``(question, sql)`` pairs the user confirmed correct
            for this dataset (thumbs-up feedback), injected as ground truth.
    """

    sqlite_path: str
    schema_summary: str = ""
    business_context: str = ""
    golden_examples: tuple[tuple[str, str], ...] = ()

    @property
    def database_uri(self) -> str:
        """SQLAlchemy URI for this dataset's SQLite file."""
        return f"sqlite:///{self.sqlite_path}"


def build_model(config: EngineConfig) -> BaseChatModel:
    """Instantiate a chat model from an engine config.

    Args:
        config: The provider/model/key selection.

    Returns:
        A deterministic (``temperature=0``) chat model.

    Raises:
        ValueError: If the provider is unknown.
    """
    if config.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.model,
            temperature=settings.temperature,
            base_url=settings.ollama_base_url,
        )

    if config.provider in _CLOUD_PROVIDERS:
        from langchain_openai import ChatOpenAI

        kwargs: dict = {
            "model": config.model,
            "temperature": settings.temperature,
            "api_key": config.api_key,
        }
        if config.provider == "openrouter":
            kwargs["base_url"] = OPENROUTER_BASE_URL
        kwargs.update(_insecure_http_clients())
        return ChatOpenAI(**kwargs)

    raise ValueError(f"Unknown provider: {config.provider!r}")


def _insecure_http_clients() -> dict:
    """Return http client kwargs that skip TLS verification, or ``{}``.

    Only active when ``settings.insecure_tls`` is set — a dev-only escape hatch
    for TLS-intercepting networks. In every normal deployment this returns an
    empty dict and the default, verifying clients are used.
    """
    if not settings.insecure_tls:
        return {}
    import httpx

    return {
        "http_client": httpx.Client(verify=False),
        "http_async_client": httpx.AsyncClient(verify=False),
    }


def build_agent_for(
    config: EngineConfig,
    *,
    user_preferences: str = "",
    fallback: BaseChatModel | None = None,
    dataset: DatasetContext | None = None,
) -> CompiledStateGraph:
    """Assemble a compiled agent for the chosen engine.

    Local engines keep the escalate-on-degenerate safety net (falling back to
    ``fallback`` when provided); cloud engines run without one.

    Args:
        config: The provider/model/key selection.
        user_preferences: Free text appended to the system prompt.
        fallback: Optional cloud model used as the escalation target for a
            local primary.
        dataset: The uploaded dataset to query (hosted mode). When ``None`` the
            agent runs against the configured Northwind database (POC) with the
            Northwind-specific prompt and the ``search_docs`` knowledge tool.

    Returns:
        A compiled LangGraph agent ready to stream.
    """
    model = build_model(config)
    db = build_database(dataset.database_uri if dataset else None)
    sql_tools = SQLDatabaseToolkit(db=db, llm=model).get_tools()

    if config.is_local:
        # Lean local path: drop the LLM-backed query checker. It is a full extra
        # model round-trip to lint SQL the model already wrote — negligible value
        # on a small local model, and the dominant latency cost (it is the step
        # that stalls when a slow local run is cancelled mid-stream).
        sql_tools = [t for t in sql_tools if t.name != "sql_db_query_checker"]

    system_prompt = build_system_prompt(
        is_local=config.is_local,
        supports_charts=config.supports_charts,
        user_preferences=user_preferences,
        dataset_summary=dataset.schema_summary if dataset else None,
        business_context=dataset.business_context if dataset else "",
        golden_examples=dataset.golden_examples if dataset else (),
    )

    # The Northwind knowledge base (search_docs) is POC-only; an uploaded
    # dataset carries its own context via the schema summary + business context.
    tools = sql_tools if dataset else sql_tools + [search_docs]

    # Local models have a tight context, so the trim is the load-bearing guard;
    # cloud models get a large budget so the curated multi-turn history the
    # frontend sends survives untouched.
    budget = (
        settings.max_context_tokens
        if config.is_local
        else settings.max_context_tokens_cloud
    )
    middleware: list = [make_trim_context(budget)]
    if config.is_local and fallback is not None:
        # Keep the local-first / escalate-on-empty design for local runs.
        middleware.insert(0, EscalateToFallbackMiddleware(fallback))

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=None,
        middleware=middleware,
    )
