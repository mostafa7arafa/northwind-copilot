"""Northwind Copilot — a local-first natural-language-to-SQL agent.

The package is organised in domain-driven layers:

* :mod:`northwind_copilot.domain` — business language: KPI/revenue definitions
  and the analyst system prompt.
* :mod:`northwind_copilot.application` — orchestration: the agent graph and the
  middleware that governs model fallback and context trimming.
* :mod:`northwind_copilot.infrastructure` — adapters to external systems: the
  LLMs, the SQL database, the vector store, and the document-search tool.
"""
