"""Core layer: the business language and configuration.

Holds the settings singleton, the KPI/revenue definitions, and every analyst
prompt (static and request-scoped). Nothing here reaches out to a database, an
LLM, or the network — it is pure configuration and text.
"""
