"""Capture a streamed turn's artifacts and persist conversations/turns.

``TurnRecorder`` observes the same SSE events the client renders and accumulates
them into a storable shape. The chat endpoint drives it as it streams and calls
:func:`persist_turn` in a ``finally`` block, so a turn is saved even if the
client disconnects mid-stream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.persistence.models import Conversation, Turn


class TurnRecorder:
    """Accumulate pipeline events into the fields of one stored turn."""

    def __init__(self) -> None:
        self.provider = ""
        self.model = ""
        self.answer = ""
        self._queries: dict[int, dict[str, Any]] = {}
        self.charts: list[dict] = []
        self.insights: dict | None = None
        self.error: dict | None = None

    def observe(self, event: dict) -> None:
        """Fold one SSE event into the accumulating turn."""
        etype = event.get("type")
        if etype == "engine":
            self.provider = event.get("provider", "")
            self.model = event.get("model", "")
        elif etype == "sql":
            self._queries.setdefault(event.get("seq", 0), {})["sql"] = event.get("sql")
        elif etype == "table":
            entry = self._queries.setdefault(event.get("seq", 0), {})
            entry["table"] = {
                "columns": event.get("columns", []),
                "rows": event.get("rows", []),
                "truncated": event.get("truncated", False),
            }
        elif etype == "chart":
            self.charts.append(event.get("option", {}))
        elif etype == "insights":
            self.insights = {
                "text": event.get("text", ""),
                "bullets": event.get("bullets", []),
            }
        elif etype == "final":
            self.answer = event.get("text", "")
        elif etype == "error":
            self.error = {
                "message": event.get("message", ""),
                "detail": event.get("detail", ""),
            }

    @property
    def queries(self) -> list[dict]:
        """Return executed queries with their tables, ordered by sequence."""
        return [self._queries[seq] for seq in sorted(self._queries)]


async def ensure_conversation(
    session: AsyncSession,
    *,
    dataset_id: str | None,
    conversation_id: str | None,
    title_hint: str,
) -> Conversation:
    """Return the caller's conversation, creating one if needed.

    Args:
        session: An open application-database session.
        dataset_id: The dataset this conversation is about, if any.
        conversation_id: An existing conversation to append to, if provided.
        title_hint: Text (usually the first question) to title a new thread.

    Returns:
        A persisted :class:`Conversation`.

    Raises:
        ValueError: If the conversation is missing or its dataset conflicts.
    """
    if conversation_id:
        convo = await session.get(Conversation, conversation_id)
        if convo is None:
            raise ValueError("conversation not found")
        if dataset_id is not None and convo.dataset_id != dataset_id:
            raise ValueError("conversation dataset mismatch")
        return convo
    convo = Conversation(
        dataset_id=dataset_id,
        title=(title_hint.strip()[:42] or "New analysis"),
    )
    session.add(convo)
    await session.flush()
    return convo


async def persist_turn(
    session: AsyncSession,
    *,
    conversation_id: str,
    question: str,
    recorder: TurnRecorder,
    turn_id: str | None = None,
    reserved_turn: Turn | None = None,
) -> Turn:
    """Create a turn or fill the row reserved before its SSE response starts."""
    if reserved_turn is not None and (
        reserved_turn.id != turn_id or reserved_turn.conversation_id != conversation_id
    ):
        raise ValueError("Turn reservation does not match the conversation.")
    turn = (
        reserved_turn
        if reserved_turn is not None
        else Turn(id=turn_id, conversation_id=conversation_id)
    )
    turn.question = question
    turn.answer = recorder.answer
    turn.queries = recorder.queries
    turn.charts = recorder.charts
    turn.insights = recorder.insights
    turn.error = recorder.error
    turn.model = recorder.model
    turn.provider = recorder.provider
    session.add(turn)
    await session.flush()
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(timezone.utc))
    )
    return turn
