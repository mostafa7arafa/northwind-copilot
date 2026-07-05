"""FastAPI application exposing the Northwind Copilot to the web frontend."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from northwind_copilot.core.config import settings
from northwind_copilot.core.observability import init_sentry
from northwind_copilot.query.agent_factory import EngineConfig, Provider
from northwind_copilot.response.streaming import stream_chat
from northwind_copilot.web.models_registry import list_all_providers
from northwind_copilot.web.preferences import load_preferences, save_preferences
from northwind_copilot.web.security import rate_limit, require_access

# Error tracking is opt-in (SENTRY_DSN) and a no-op in the POC and tests.
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown.

    In hosted mode over a local SQLite app DB (dev/test), create the schema on
    startup so no separate migration step is needed. Production runs Postgres
    and manages the schema with Alembic, so ``create_all`` is intentionally
    skipped there to avoid drifting from the migration history.
    """
    if settings.hosted_mode and settings.app_db_url.startswith("sqlite"):
        from northwind_copilot.tenancy.db import create_all

        await create_all()
    yield


app = FastAPI(title="Northwind Copilot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Identity + dataset routes are always mounted; they are only *reachable* in
# hosted mode (the POC frontend never calls them, and they touch the app DB
# only when invoked).
from northwind_copilot.auth.router import router as auth_router  # noqa: E402
from northwind_copilot.conversations.router import (  # noqa: E402
    router as conversations_router,
)
from northwind_copilot.datasets.router import router as datasets_router  # noqa: E402
from northwind_copilot.keys.router import router as keys_router  # noqa: E402

app.include_router(auth_router)
app.include_router(datasets_router)
app.include_router(conversations_router)
app.include_router(keys_router)


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
    # Hosted mode: which uploaded dataset to query. Ignored in the POC (which
    # always queries the configured Northwind database).
    dataset_id: str | None = Field(default=None, max_length=36)
    # Hosted mode: the conversation to append this turn to (a new one is created
    # when omitted). Prior history is rebuilt server-side from stored turns.
    conversation_id: str | None = Field(default=None, max_length=36)


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


@app.get("/api/usage")
async def usage(ctx=Depends(require_access)) -> dict:
    """The caller org's plan and remaining allowance (drives the UsageMeter).

    In the POC (no tenant) this returns ``{"hosted": false}`` so the frontend
    can simply not render a meter.
    """
    if ctx is None:
        return {"hosted": False}
    from northwind_copilot.billing.entitlements import get_entitlements
    from northwind_copilot.metering.credits import trial_queries_used
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import Org

    ent = get_entitlements(ctx.plan)
    async with get_sessionmaker()() as session:
        org = await session.get(Org, ctx.org_id)
        used = await trial_queries_used(session, ctx.org_id)
        from northwind_copilot.keys.service import list_keys

        byok_providers = [k.provider for k in await list_keys(session, ctx.org_id)]
    trial_ends = org.trial_ends_at.isoformat() if org and org.trial_ends_at else None
    return {
        "hosted": True,
        "plan": ctx.plan,
        "credits_remaining": float(org.credit_balance) if org else 0.0,
        "credits_per_month": ent.credits_per_month,
        "trial_queries_used": used,
        "trial_queries_limit": ent.trial_queries,
        "trial_ends_at": trial_ends,
        "byok_providers": byok_providers,
    }


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
    # Use the server's own key only for *trusted* callers: authenticated
    # hosted-mode users, or a shared-token deployment. An anonymous open POC
    # deployment never spends the operator's key for a caller who didn't bring
    # one. (Local Ollama needs no key and is unaffected.)
    if not (settings.hosted_mode or settings.auth_token):
        return None
    env_var = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}.get(
        provider, ""
    )
    return os.getenv(env_var) if env_var else None


async def _resolve_hosted_key(
    provider: str, browser_key: str | None, ctx
) -> tuple[str | None, bool]:
    """Resolve the key for a hosted turn, distinguishing BYOK from metered.

    Resolution order: the org's stored (encrypted) key, then a key supplied in
    the request body — both are the customer's own account, so those turns are
    BYOK (recorded but never charged). Only when neither exists does the turn
    run on the server's key and get metered.

    Returns:
        ``(api_key, byok)``.
    """
    if provider not in ("openai", "openrouter"):
        return None, False  # Local Ollama: no key, nothing to meter against.
    from northwind_copilot.keys.service import resolve_org_key
    from northwind_copilot.tenancy.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        stored = await resolve_org_key(session, org_id=ctx.org_id, provider=provider)
    if stored:
        return stored, True
    if browser_key:
        return browser_key, True
    return _resolve_api_key(provider, None), False


async def _resolve_dataset(dataset_id: str | None, ctx) -> object | None:
    """Load the requested dataset as a ``DatasetContext``, scoped to the org.

    Args:
        dataset_id: The dataset the caller asked to query, if any.
        ctx: The request's ``RequestContext`` (hosted mode) or ``None`` (POC).

    Returns:
        A ``DatasetContext`` when a ready, owned dataset is requested; ``None``
        for the POC path.

    Raises:
        HTTPException: 404 if the dataset is missing or not the org's; 409 if it
            is not finished ingesting.
    """
    if not (ctx and dataset_id):
        return None
    from fastapi import HTTPException, status

    from northwind_copilot.query.agent_factory import DatasetContext
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import Dataset

    async with get_sessionmaker()() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None or dataset.org_id != ctx.org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found."
            )
        if dataset.status != "ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dataset is still being prepared.",
            )
        return DatasetContext(
            sqlite_path=dataset.file_path,
            schema_summary=dataset.schema_summary,
            business_context=dataset.business_context,
        )


def _last_question(messages: list[Message]) -> str:
    """Return the content of the last user message (this turn's question)."""
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


async def _prepare_conversation(body: ChatRequest, ctx) -> tuple[str, list[dict]]:
    """Resolve/create the conversation and rebuild history from stored turns.

    Server-owned history closes the client-forged-history hole: only the new
    question is taken from the request; all prior context comes from the DB.

    Returns:
        ``(conversation_id, history)``.
    """
    from sqlalchemy import select

    from northwind_copilot.conversations.history import build_history
    from northwind_copilot.conversations.service import ensure_conversation
    from northwind_copilot.tenancy.db import get_sessionmaker
    from northwind_copilot.tenancy.models import Turn

    question = _last_question(body.messages)
    async with get_sessionmaker()() as session:
        try:
            convo = await ensure_conversation(
                session,
                org_id=ctx.org_id,
                user_id=ctx.user_id,
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
        await session.commit()
        return convo.id, history


async def _check_allowance(ctx, byok: bool) -> None:
    """Run the pre-flight credit/trial check for a hosted turn (402 on fail)."""
    from northwind_copilot.metering.credits import check_and_reserve
    from northwind_copilot.tenancy.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        await check_and_reserve(session, org_id=ctx.org_id, plan=ctx.plan, byok=byok)


@app.post("/api/chat", dependencies=[Depends(rate_limit)])
async def chat(
    body: ChatRequest,
    ctx=Depends(require_access),
) -> StreamingResponse:
    """Stream one analyst turn as Server-Sent Events of pipeline stages.

    ``ctx`` is a ``RequestContext`` in hosted mode (used to scope dataset access
    and persist the conversation) or ``None`` in the single-user POC.
    """
    byok = False
    if ctx:
        api_key, byok = await _resolve_hosted_key(body.provider, body.api_key, ctx)
        # Out-of-allowance turns are rejected before any model call is made.
        await _check_allowance(ctx, byok)
    else:
        api_key = _resolve_api_key(body.provider, body.api_key)
    config = EngineConfig(provider=body.provider, model=body.model, api_key=api_key)
    prefs = load_preferences()
    fallback = _build_fallback() if config.is_local else None
    dataset = await _resolve_dataset(body.dataset_id, ctx)

    # Hosted mode: server owns history + persistence. POC: client sends history,
    # nothing is stored.
    conversation_id: str | None = None
    if ctx:
        conversation_id, history = await _prepare_conversation(body, ctx)
    else:
        history = [m.model_dump() for m in body.messages]

    async def event_source() -> AsyncIterator[bytes]:
        recorder = None
        meter = None
        finalized = False

        async def finalize() -> dict | None:
            """Persist the turn and settle usage exactly once; return the
            usage payload, or ``None`` when there is nothing to report."""
            nonlocal finalized
            if finalized:
                return None
            finalized = True
            return await _finalize_turn(
                conversation_id=conversation_id,
                question=_last_question(body.messages),
                recorder=recorder,
                ctx=ctx,
                config=config,
                meter=meter,
                byok=byok,
            )

        if ctx:
            from northwind_copilot.conversations.service import TurnRecorder
            from northwind_copilot.metering.usage import UsageAccumulator

            recorder = TurnRecorder()
            meter = UsageAccumulator()
            # Tell the client which conversation this turn belongs to.
            yield (
                "data: "
                + json.dumps({"type": "conversation", "id": conversation_id})
                + "\n\n"
            ).encode("utf-8")
        try:
            async for event in stream_chat(
                history=history,
                config=config,
                user_preferences=prefs,
                fallback=fallback,
                session_id=body.session_id,
                dataset=dataset,
                usage_meter=meter,
            ):
                # Settle before forwarding `done` so the client learns this
                # turn's cost and the updated balance as part of the stream.
                if ctx and event.get("type") == "done":
                    usage_payload = await finalize()
                    if usage_payload is not None:
                        yield ("data: " + json.dumps(usage_payload) + "\n\n").encode(
                            "utf-8"
                        )
                if recorder is not None:
                    recorder.observe(event)
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        finally:
            # Persist + settle even on disconnect/timeout (this runs on cancel),
            # so abandoned turns are still recorded and billed.
            if ctx:
                await finalize()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _finalize_turn(
    *,
    conversation_id: str | None,
    question: str,
    recorder,
    ctx,
    config: EngineConfig,
    meter,
    byok: bool,
) -> dict | None:
    """Persist the recorded turn and settle its usage, ignoring DB failures.

    Runs in the stream's ``finally`` path, so a turn is stored and billed even
    when the client disconnects mid-answer. A DB hiccup here must not surface
    as a chat failure — the answer already streamed to the user.

    Returns:
        The ``usage`` SSE payload (``credits`` spent this turn plus the
        remaining allowance), or ``None`` when nothing was metered.
    """
    if not (ctx and conversation_id):
        return None
    from northwind_copilot.conversations.service import persist_turn
    from northwind_copilot.metering.credits import settle, trial_queries_used
    from northwind_copilot.tenancy.db import get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            turn = None
            if recorder is not None:
                turn = await persist_turn(
                    session,
                    conversation_id=conversation_id,
                    question=question,
                    recorder=recorder,
                )
            payload: dict | None = None
            # A turn that failed before any model call has no usage — don't
            # record an empty event (it would eat a trial query for nothing).
            if meter is not None and meter.has_usage:
                credits, remaining = await settle(
                    session,
                    org_id=ctx.org_id,
                    plan=ctx.plan,
                    turn_id=turn.id if turn is not None else None,
                    provider=config.provider,
                    model=config.model,
                    usage=meter,
                    byok=byok,
                )
                if remaining is None and not byok:
                    # Trial turns: "remaining" is the query allowance.
                    from northwind_copilot.billing.entitlements import (
                        get_entitlements,
                    )

                    used = await trial_queries_used(session, ctx.org_id)
                    remaining = max(0, get_entitlements(ctx.plan).trial_queries - used)
                payload = {
                    "type": "usage",
                    "credits": float(credits),
                    "remaining": float(remaining) if remaining is not None else None,
                    "byok": byok,
                }
            await session.commit()
            return payload
    except Exception:  # noqa: BLE001 - best-effort persistence
        import logging

        logging.getLogger(__name__).exception("failed to persist/settle turn")
        return None
