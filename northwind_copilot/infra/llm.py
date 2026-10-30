"""Chat model factories for the primary (local) and fallback (cloud) models."""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from northwind_copilot.core.config import settings


def build_ollama_model(model: str) -> ChatOllama:
    """Build a local Ollama chat model with the tuned runtime options.

    The three non-obvious options, all measured on this repo's SQL benchmark:

    * ``num_ctx`` — Ollama defaults to 4096 regardless of what the model
      supports, and silently truncates an over-long prompt *from the head*. The
      head is where the system prompt lives, so a long turn quietly loses its
      instructions. Pinning it to :attr:`Settings.ollama_num_ctx` (>= the trim
      budget) is a correctness fix, not just a latency one.
    * ``reasoning`` — off. Chain-of-thought cost 2.5x latency for identical
      accuracy on the benchmark (9/11 with and without, failing the same two
      questions). ``think: false`` is ignored by models without the capability,
      so this is safe for every local model.
    * ``keep_alive`` — keeps the weights resident between turns, so a
      conversation does not pay a reload per question.

    Args:
        model: The Ollama model tag (e.g. ``gemma4-12b``).

    Returns:
        A deterministic (``temperature=0``) Ollama chat model.
    """
    return ChatOllama(
        model=model,
        temperature=settings.temperature,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict,
        keep_alive=settings.ollama_keep_alive,
        reasoning=settings.ollama_reasoning,
    )


def build_primary_model() -> BaseChatModel:
    """Build the local-first primary chat model.

    Returns:
        A deterministic (``temperature=0``) Ollama chat model.
    """
    return build_ollama_model(settings.primary_model)


def apply_gpt6_reasoning(model: str, kwargs: dict) -> None:
    """Disable reasoning on a GPT-6 ChatOpenAI kwargs dict.

    GPT-6 Chat Completions requires ``reasoning_effort="none"`` when function
    tools are bound. OpenRouter ids may be prefixed with ``openai/``. Other
    models are left unchanged. ``temperature`` is not touched; callers pass it
    the same way ``build_model`` does, including for GPT-6.

    Args:
        model: Provider model id, with or without an ``openai/`` prefix.
        kwargs: Chat model constructor arguments to update in place.
    """
    model_name = model.removeprefix("openai/")
    if model_name.startswith(("gpt-6-", "gpt-6.")):
        kwargs["reasoning_effort"] = "none"


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
    kwargs: dict = {
        "model": settings.fallback_model,
        "temperature": settings.temperature,
    }
    apply_gpt6_reasoning(settings.fallback_model, kwargs)
    return ChatOpenAI(**kwargs)
