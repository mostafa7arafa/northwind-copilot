"""FastAPI application exposing the Northwind Copilot to the web frontend."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from northwind_copilot.core.config import settings
from northwind_copilot.query.agent_factory import EngineConfig, Provider
from northwind_copilot.response.streaming import stream_chat
from northwind_copilot.web.models_registry import list_all_providers
from northwind_copilot.web.preferences import load_preferences, save_preferences
from northwind_copilot.web.security import rate_limit, require_auth

app = FastAPI(title="Northwind Copilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    """One turn of conversation history."""

    role: Literal["user", "assistant", "system"]
    content: str = Field(max_length=settings.max_message_chars)


class ChatRequest(BaseModel):
    """A request to run one analyst turn."""

    messages: list[Message] = Field(min_length=1, max_length=settings.max_messages)
    session_id: str | None = Field(default=None, max_length=128)
    provider: Provider = "ollama"
    model: str = Field(default=settings.primary_model, max_length=200)
    api_key: str | None = Field(default=None, max_length=512)


class PreferencesRequest(BaseModel):
    """A request to save the user's analyst preferences."""

    preferences: str = Field(default="", max_length=settings.max_preferences_chars)

    @field_validator("preferences")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


@app.get("/api/health")
async def health() -> dict:
    """Liveness probe (unauthenticated)."""
    return {"ok": True}


@app.get("/api/models", dependencies=[Depends(require_auth)])
async def models() -> dict:
    """List local (Ollama) and cloud (OpenAI/OpenRouter) model choices."""
    return await list_all_providers()


@app.get("/api/preferences", dependencies=[Depends(require_auth)])
async def get_preferences() -> dict:
    """Return the saved analyst preferences."""
    return {"preferences": load_preferences()}


@app.post("/api/preferences", dependencies=[Depends(require_auth)])
async def put_preferences(body: PreferencesRequest) -> dict:
    """Save analyst preferences that are appended to the system prompt."""
    return {"preferences": save_preferences(body.preferences)}


def _build_fallback():
    """Build the cloud escalation model for local runs, if a key is available."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.fallback_model, temperature=settings.temperature)


def _resolve_api_key(provider: str, browser_key: str | None) -> str | None:
    """Resolve the API key for a cloud request.

    Prefer the per-request (browser) key. Only fall back to a server-side env
    key when the deployment is gated behind an auth token — otherwise an
    anonymous visitor could spend the operator's credits on an open deployment.

    Args:
        provider: The chosen cloud provider.
        browser_key: The key supplied in the request body, if any.

    Returns:
        The resolved key, or ``None`` if none is available/allowed.
    """
    if browser_key:
        return browser_key
    if not settings.auth_token:
        # Open deployment: never spend the server's own key for a caller who
        # didn't bring one. (Local Ollama needs no key and is unaffected.)
        return None
    env_var = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(
        provider, ""
    )
    return os.getenv(env_var) if env_var else None


@app.post(
    "/api/chat",
    dependencies=[Depends(require_auth), Depends(rate_limit)],
)
async def chat(body: ChatRequest) -> StreamingResponse:
    """Stream one analyst turn as Server-Sent Events of pipeline stages."""
    config = EngineConfig(
        provider=body.provider,
        model=body.model,
        api_key=_resolve_api_key(body.provider, body.api_key),
    )
    prefs = load_preferences()
    fallback = _build_fallback() if config.is_local else None

    async def event_source() -> AsyncIterator[bytes]:
        history = [m.model_dump() for m in body.messages]
        async for event in stream_chat(
            history=history,
            config=config,
            user_preferences=prefs,
            fallback=fallback,
            session_id=body.session_id,
        ):
            yield f"data: {json.dumps(event)}\n\n".encode("utf-8")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
