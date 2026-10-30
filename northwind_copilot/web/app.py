"""Local single-user API for uploaded data and saved analyst conversations."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from anyio import CancelScope
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from northwind_copilot.conversations.router import router as conversations_router
from northwind_copilot.conversations.service import TurnRecorder, persist_turn
from northwind_copilot.core.config import settings
from northwind_copilot.core.observability import init_sentry
from northwind_copilot.datasets.router import router as datasets_router
from northwind_copilot.persistence.db import (
    create_all,
    dispose_engine,
    get_sessionmaker,
)
from northwind_copilot.query.agent_factory import EngineConfig, Provider
from northwind_copilot.response.streaming import stream_chat
from northwind_copilot.web.models_registry import list_all_providers
from northwind_copilot.web.preferences import load_preferences, save_preferences
from northwind_copilot.web.security import rate_limit, require_access

init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the local workspace schema and release connections on shutdown."""
    await create_all()
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="Northwind Copilot API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(datasets_router)
app.include_router(conversations_router)


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
    # Omit for the built-in Northwind sample.
    dataset_id: str | None = Field(default=None, max_length=36)
    # Omit to create a saved conversation; history is always server-owned.
    conversation_id: str | None = Field(default=None, max_length=36)
    # Stable browser ID lets interrupted turns reconcile after a missed SSE event.
    turn_id: str | None = Field(
        default=None, min_length=1, max_length=36, pattern=r"^[A-Za-z0-9_-]+$"
    )


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


@app.get("/api/models", dependencies=[Depends(require_access)])
async def models() -> dict:
    """List local (Ollama) and cloud (OpenAI/OpenRouter) model choices."""
    return await list_all_providers()


@app.get("/api/preferences", dependencies=[Depends(require_access)])
async def get_preferences() -> dict:
    """Return the saved analyst preferences."""
    return {"preferences": load_preferences()}


@app.post("/api/preferences", dependencies=[Depends(require_access)])
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
    """Prefer a memory-only browser key, then the local operator's .env key.

    Called only after the loopback/origin guard has accepted the request.
    """
    if browser_key:
        return browser_key
    env_var = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(
        provider
    )
    return os.getenv(env_var) if env_var else None


async def _resolve_dataset(dataset_id: str | None, question: str = "") -> object | None:
    """Load a ready dataset, or use the built-in Northwind sample when omitted."""
    if not dataset_id:
        return None
    from fastapi import HTTPException, status

    from northwind_copilot.datasets.golden import select_examples
    from northwind_copilot.persistence.db import get_sessionmaker
    from northwind_copilot.persistence.models import Dataset
    from northwind_copilot.query.agent_factory import DatasetContext

    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found."
            )
        if dataset.status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dataset is still being prepared.",
            )
        examples = await select_examples(session, dataset.id, question)
        return DatasetContext(
            sqlite_path=dataset.file_path,
            schema_summary=dataset.schema_summary,
            business_context=dataset.business_context,
            golden_examples=tuple(examples),
        )


def _last_question(messages: list[Message]) -> str:
    """Return the content of the last user message (this turn's question)."""
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


async def _prepare_conversation(
    body: ChatRequest,
) -> tuple[str, list[dict], str | None, str]:
    """Resolve history and reserve a unique turn before sending SSE headers.

    Server-owned history closes the client-forged-history hole: only the new
    question is taken from the request; all prior context comes from the DB.

    Returns:
        ``(conversation_id, history, dataset_id, turn_id)``.
    """
    from sqlalchemy import select

    from northwind_copilot.conversations.history import build_history
    from northwind_copilot.conversations.service import ensure_conversation
    from northwind_copilot.persistence.db import get_sessionmaker
    from northwind_copilot.persistence.models import Turn

    question = _last_question(body.messages)
    async with get_sessionmaker()() as session:
        try:
            convo = await ensure_conversation(
                session,
                dataset_id=body.dataset_id,
                conversation_id=body.conversation_id,
                title_hint=question,
            )
        except ValueError:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
            )
        # Query turns explicitly rather than touching the lazy `convo.turns`
        # relationship, which would trigger a lazy load in async context
        # (sqlalchemy MissingGreenlet).
        turns = (
            (
                await session.execute(
                    select(Turn)
                    .where(Turn.conversation_id == convo.id)
                    .order_by(Turn.created_at)
                )
            )
            .scalars()
            .all()
        )
        history = build_history(list(turns), question)
        recorder = TurnRecorder()
        recorder.provider, recorder.model = body.provider, body.model
        try:
            turn = await persist_turn(
                session,
                conversation_id=convo.id,
                turn_id=body.turn_id,
                question=question,
                recorder=recorder,
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if body.turn_id and await session.get(Turn, body.turn_id) is not None:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=409, detail="Turn already exists."
                ) from None
            raise
        return convo.id, history, convo.dataset_id, turn.id


@app.post("/api/chat", dependencies=[Depends(require_access), Depends(rate_limit)])
async def chat(body: ChatRequest) -> StreamingResponse:
    """Stream one turn, using persisted history and saving all artifacts."""
    # Validate before creating a thread so invalid datasets don't leave empty chats.
    dataset = await _resolve_dataset(body.dataset_id, _last_question(body.messages))
    conversation_id, history, dataset_id, turn_id = await _prepare_conversation(body)
    if dataset_id != body.dataset_id:
        dataset = await _resolve_dataset(dataset_id, _last_question(body.messages))
    config = EngineConfig(
        provider=body.provider,
        model=body.model,
        api_key=_resolve_api_key(body.provider, body.api_key),
    )
    prefs = load_preferences()
    fallback = _build_fallback() if config.is_local else None

    async def event_source() -> AsyncIterator[bytes]:
        recorder = TurnRecorder()
        finalized = False

        async def finalize() -> str | None:
            nonlocal finalized
            if finalized:
                return None
            finalized = True
            # Shield both normal completion and disconnect finalization from
            # Starlette's cancelled stream task group until the write finishes.
            with CancelScope(shield=True):
                return await _finalize_turn(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    question=_last_question(body.messages),
                    recorder=recorder,
                )

        yield _sse({"type": "conversation", "id": conversation_id})
        try:
            async for event in stream_chat(
                history=history,
                config=config,
                user_preferences=prefs,
                fallback=fallback,
                session_id=body.session_id,
                dataset=dataset,
            ):
                if event.get("type") == "done":
                    saved_turn_id = await finalize()
                    if saved_turn_id is not None:
                        yield _sse({"type": "turn", "id": saved_turn_id})
                recorder.observe(event)
                yield _sse(event)
        finally:
            await finalize()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


async def _finalize_turn(
    *, conversation_id: str, turn_id: str, question: str, recorder: TurnRecorder
) -> str | None:
    """Best-effort persistence, including interrupted streams."""
    try:
        from northwind_copilot.persistence.models import Turn

        async with get_sessionmaker()() as session:
            reserved_turn = await session.get(Turn, turn_id)
            if reserved_turn is None:
                raise ValueError("Turn reservation no longer exists.")
            turn = await persist_turn(
                session,
                reserved_turn=reserved_turn,
                conversation_id=conversation_id,
                turn_id=turn_id,
                question=question,
                recorder=recorder,
            )
            await session.commit()
            return turn.id
    except Exception:  # noqa: BLE001 - answer may already have streamed
        import logging

        logging.getLogger(__name__).exception("failed to persist turn")
        return None
