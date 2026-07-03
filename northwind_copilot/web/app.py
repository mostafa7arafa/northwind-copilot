"""FastAPI application exposing the Northwind Copilot to the web frontend."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from northwind_copilot.core.config import settings
from northwind_copilot.query.agent_factory import EngineConfig
from northwind_copilot.response.streaming import stream_chat
from northwind_copilot.web.models_registry import list_all_providers
from northwind_copilot.web.preferences import load_preferences, save_preferences

app = FastAPI(title="Northwind Copilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    """One turn of conversation history."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """A request to run one analyst turn."""

    messages: list[Message]
    session_id: str | None = None
    provider: str = "ollama"
    model: str = Field(default=settings.primary_model)
    api_key: str | None = None


class PreferencesRequest(BaseModel):
    """A request to save the user's analyst preferences."""

    preferences: str = ""


@app.get("/api/health")
async def health() -> dict:
    """Liveness probe."""
    return {"ok": True}


@app.get("/api/models")
async def models() -> dict:
    """List local (Ollama) and cloud (OpenAI/OpenRouter) model choices."""
    return await list_all_providers()


@app.get("/api/preferences")
async def get_preferences() -> dict:
    """Return the saved analyst preferences."""
    return {"preferences": load_preferences()}


@app.post("/api/preferences")
async def put_preferences(body: PreferencesRequest) -> dict:
    """Save analyst preferences that are appended to the system prompt."""
    return {"preferences": save_preferences(body.preferences)}


def _build_fallback():
    """Build the cloud escalation model for local runs, if a key is available."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.fallback_model, temperature=settings.temperature)


@app.post("/api/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    """Stream one analyst turn as Server-Sent Events of pipeline stages."""
    # Prefer the per-request (browser) key; otherwise fall back to a server-side
    # env key for the chosen cloud provider.
    _ENV_KEY_BY_PROVIDER = {
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    config = EngineConfig(
        provider=body.provider,  # type: ignore[arg-type]
        model=body.model,
        api_key=body.api_key or os.getenv(_ENV_KEY_BY_PROVIDER.get(body.provider, "")),
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
