"""Build a request-scoped agent for a chosen provider and model.

The static ``northwind_copilot.application.graph.graph`` always uses the
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

from northwind_copilot.application.middleware import (
    EscalateToFallbackMiddleware,
    make_trim_context,
)
from northwind_copilot.config import settings
from northwind_copilot.infrastructure.database import build_database
from northwind_copilot.infrastructure.tools.docs_tool import search_docs
from server.prompts import build_system_prompt

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

        return ChatOllama(model=config.model, temperature=settings.temperature)

    if config.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model,
            temperature=settings.temperature,
            api_key=config.api_key,
        )

    if config.provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model,
            temperature=settings.temperature,
            api_key=config.api_key,
            base_url=OPENROUTER_BASE_URL,
        )

    raise ValueError(f"Unknown provider: {config.provider!r}")


def build_agent_for(
    config: EngineConfig,
    *,
    user_preferences: str = "",
    fallback: BaseChatModel | None = None,
) -> CompiledStateGraph:
    """Assemble a compiled agent for the chosen engine.

    Local engines keep the escalate-on-degenerate safety net (falling back to
    ``fallback`` when provided); cloud engines run without one.

    Args:
        config: The provider/model/key selection.
        user_preferences: Free text appended to the system prompt.
        fallback: Optional cloud model used as the escalation target for a
            local primary.

    Returns:
        A compiled LangGraph agent ready to stream.
    """
    model = build_model(config)
    db = build_database()
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
    )

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
        tools=sql_tools + [search_docs],
        system_prompt=system_prompt,
        checkpointer=None,
        middleware=middleware,
    )
