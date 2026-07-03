"""Discover the models the user can pick from.

Local models are read live from the machine's Ollama daemon; cloud models are a
small curated list per provider (the full catalogue is large and churns, so we
surface sensible analyst-grade defaults and let the user type any id).
"""

from __future__ import annotations

import os

import httpx

from northwind_copilot.core.config import settings

OLLAMA_TAGS_URL = f"{settings.ollama_base_url.rstrip('/')}/api/tags"

# Curated cloud defaults. The frontend also allows a free-typed model id.
CURATED_OPENAI = [
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini", "note": "fast, cheap"},
    {"id": "gpt-4.1", "label": "GPT-4.1", "note": "strongest reasoning"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "note": "budget"},
]

CURATED_OPENROUTER = [
    {"id": "anthropic/claude-sonnet-4", "label": "Claude Sonnet 4", "note": "balanced"},
    {"id": "openai/gpt-4.1-mini", "label": "GPT-4.1 mini", "note": "fast"},
    {"id": "google/gemini-2.0-flash-001", "label": "Gemini 2.0 Flash", "note": "cheap"},
    {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "label": "Llama 3.3 70B",
        "note": "open",
    },
]


async def list_ollama_models() -> list[dict]:
    """Query the local Ollama daemon for installed models.

    Returns:
        A list of ``{"id", "label", "note"}`` dicts, or an empty list if the
        daemon is unreachable (Ollama not running / not installed).
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(OLLAMA_TAGS_URL)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    models: list[dict] = []
    for entry in data.get("models", []):
        name = entry.get("name") or entry.get("model")
        if not name:
            continue
        size = entry.get("size")
        note = f"{size / 1e9:.1f} GB" if isinstance(size, (int, float)) else "local"
        models.append({"id": name, "label": name, "note": note})
    return models


async def list_all_providers() -> dict:
    """Assemble the full provider/model registry for the dashboard.

    Returns:
        A dict keyed by provider with ``available`` flags and model lists.
    """
    ollama = await list_ollama_models()
    return {
        "local": {
            "provider": "ollama",
            "available": bool(ollama),
            "models": ollama,
        },
        "cloud": [
            {
                "provider": "openai",
                "label": "OpenAI",
                # A browser key is only *needed* when the server has none in env.
                "needs_key": not bool(os.getenv("OPENAI_API_KEY")),
                "models": CURATED_OPENAI,
            },
            {
                "provider": "openrouter",
                "label": "OpenRouter",
                "needs_key": not bool(os.getenv("OPENROUTER_API_KEY")),
                "models": CURATED_OPENROUTER,
            },
        ],
    }
