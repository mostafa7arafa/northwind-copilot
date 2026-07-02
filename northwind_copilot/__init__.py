"""Northwind Copilot — a local-first natural-language-to-SQL agent.

The package is organised in domain-driven layers:

* :mod:`northwind_copilot.domain` — business language: KPI/revenue definitions
  and the analyst system prompt.
* :mod:`northwind_copilot.application` — orchestration: the agent graph and the
  middleware that governs model fallback and context trimming.
* :mod:`northwind_copilot.infrastructure` — adapters to external systems: the
  LLMs, the SQL database, the vector store, and the document-search tool.
"""

from __future__ import annotations

import warnings

# ChatOllama carries a `_serialized` attribute outside Pydantic's declared
# fields. LangGraph serializes the model instance when it snapshots graph state,
# so Pydantic emits a harmless "Unexpected field `_serialized`" warning on every
# agent step. Filtered here — the package root — so it is silenced for every
# entrypoint (the static graph, the benchmark, and the FastAPI server) alike.
warnings.filterwarnings(
    "ignore",
    message=".*_serialized.*",
    category=UserWarning,
    module="pydantic.main",
)
