"""FastAPI service that fronts the Northwind Copilot agent.

This package wraps the existing LangGraph agent (``northwind_copilot``) with an
HTTP API the web frontend talks to: dynamic model selection (local Ollama,
OpenAI, or OpenRouter), a streaming chat endpoint that emits structured
pipeline events, and user-preference injection into the system prompt.
"""
