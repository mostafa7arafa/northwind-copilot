"""Chat model factories for the primary (local) and fallback (cloud) models."""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from northwind_copilot.core.config import settings


def build_primary_model() -> BaseChatModel:
    """Build the local-first primary chat model.

    Returns:
        A deterministic (``temperature=0``) Ollama chat model.
    """
    return ChatOllama(model=settings.primary_model, temperature=settings.temperature)


def build_fallback_model() -> BaseChatModel | None:
    """Build the cloud fallback chat model, if a key is configured.

    ``ChatOpenAI`` raises at construction when no API key is present, so a
    local-only user without an ``OPENAI_API_KEY`` would otherwise be unable to
    even *build* the graph. The fallback is a safety net, not a requirement:
    when no key is set we return ``None`` and the agent runs without an
    escalation target.

    Returns:
        A deterministic (``temperature=0``) OpenAI chat model used when the
        primary errors or returns a degenerate response, or ``None`` when no
        ``OPENAI_API_KEY`` is available.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return ChatOpenAI(model=settings.fallback_model, temperature=settings.temperature)
