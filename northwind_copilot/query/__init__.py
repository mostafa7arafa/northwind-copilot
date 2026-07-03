"""Query layer: turn a natural-language question into a running SQL agent.

The static local-first graph (:mod:`~northwind_copilot.query.graph`), the
per-request engine builder (:mod:`~northwind_copilot.query.agent_factory`), and
the middleware that governs model fallback and context trimming.
"""
