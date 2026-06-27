"""Composition root: assemble the Northwind Copilot agent graph."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langgraph.graph.state import CompiledStateGraph

from northwind_copilot.application.middleware import (
    EscalateToFallbackMiddleware,
    trim_context,
)
from northwind_copilot.domain.prompts import SYSTEM_PROMPT
from northwind_copilot.infrastructure.database import build_database
from northwind_copilot.infrastructure.llm import (
    build_fallback_model,
    build_primary_model,
)
from northwind_copilot.infrastructure.tools.docs_tool import search_docs


def build_agent() -> CompiledStateGraph:
    """Build the agent graph: local-first model with SQL + doc-search tools.

    Returns:
        The compiled LangGraph agent, ready to ``invoke``.
    """
    primary = build_primary_model()
    fallback = build_fallback_model()

    db = build_database()
    sql_tools = SQLDatabaseToolkit(db=db, llm=primary).get_tools()

    return create_agent(
        model=primary,
        tools=sql_tools + [search_docs],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=None,
        middleware=[
            EscalateToFallbackMiddleware(fallback),
            trim_context,
        ],
    )


graph = build_agent()
"""Module-level compiled graph referenced by ``langgraph.json``."""
