"""Northwind Copilot — a local-first natural-language-to-SQL agent.

The whole project lives in this one package, split into concern-focused layers:

* :mod:`northwind_copilot.core` — business language: settings, KPI/revenue
  definitions, and every analyst prompt (static and request-scoped).
* :mod:`northwind_copilot.infra` — adapters to external systems: the LLMs, the
  SQL database, the vector store, and the ``search_docs`` tool.
* :mod:`northwind_copilot.query` — turning a question into a running SQL agent:
  the static graph, the per-request engine builder, and the middleware.
* :mod:`northwind_copilot.response` — turning agent output into the answer: a
  clean result table, an inferred chart, and the streamed pipeline events.
* :mod:`northwind_copilot.web` — the FastAPI service the frontend talks to.
* :mod:`northwind_copilot.eval` — the benchmark harness and its graders.
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
