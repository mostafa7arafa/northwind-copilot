"""Conversation management API: list, read (with turns), rename, delete.

Every route is org-scoped, so one tenant can never read another's history.
Conversations are created implicitly by the chat endpoint, not here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from northwind_copilot.tenancy.db import get_session
from northwind_copilot.tenancy.deps import RequestContext, current_org
from northwind_copilot.tenancy.models import Conversation

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    """A conversation summary (no turns)."""

    id: str
    title: str
    dataset_id: str | None
    turn_count: int


class TurnOut(BaseModel):
    """One persisted turn with its artifacts."""

    id: str
    question: str
    answer: str
    queries: list
    charts: list
    insights: dict | None
    error: dict | None
    model: str
    provider: str


class ConversationDetail(ConversationOut):
    """A conversation with its full turn history."""

    turns: list[TurnOut]


class RenameRequest(BaseModel):
    """A conversation rename."""

    title: str = Field(min_length=1, max_length=200)


async def _load_owned(
    session: AsyncSession, conversation_id: str, ctx: RequestContext
) -> Conversation:
    """Fetch a conversation (with turns), enforcing org ownership."""
    convo = (
        await session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.turns))
        )
    ).scalar_one_or_none()
    if convo is None or convo.org_id != ctx.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return convo


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    """List the org's conversations, most recently updated first."""
    convos = (
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.org_id == ctx.org_id)
                .options(selectinload(Conversation.turns))
                .order_by(Conversation.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        ConversationOut(
            id=c.id, title=c.title, dataset_id=c.dataset_id, turn_count=len(c.turns)
        )
        for c in convos
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    """Return a conversation and its turns."""
    convo = await _load_owned(session, conversation_id, ctx)
    return ConversationDetail(
        id=convo.id,
        title=convo.title,
        dataset_id=convo.dataset_id,
        turn_count=len(convo.turns),
        turns=[
            TurnOut(
                id=t.id,
                question=t.question,
                answer=t.answer,
                queries=t.queries or [],
                charts=t.charts or [],
                insights=t.insights,
                error=t.error,
                model=t.model,
                provider=t.provider,
            )
            for t in convo.turns
        ],
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    """Rename a conversation."""
    convo = await _load_owned(session, conversation_id, ctx)
    convo.title = body.title.strip()
    return ConversationOut(
        id=convo.id,
        title=convo.title,
        dataset_id=convo.dataset_id,
        turn_count=len(convo.turns),
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    ctx: RequestContext = Depends(current_org),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a conversation and its turns."""
    convo = await _load_owned(session, conversation_id, ctx)
    await session.delete(convo)
