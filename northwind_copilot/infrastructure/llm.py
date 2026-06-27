"""Chat model factories for the primary (local) and fallback (cloud) models."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from northwind_copilot.config import settings


def build_primary_model() -> BaseChatModel:
    """Build the local-first primary chat model.

    Returns:
        A deterministic (``temperature=0``) Ollama chat model.
    """
    return ChatOllama(model=settings.primary_model, temperature=settings.temperature)


def build_fallback_model() -> BaseChatModel:
    """Build the cloud fallback chat model.

    Returns:
        A deterministic (``temperature=0``) OpenAI chat model, used when the
        primary model errors or returns a degenerate response.
    """
    return ChatOpenAI(model=settings.fallback_model, temperature=settings.temperature)
