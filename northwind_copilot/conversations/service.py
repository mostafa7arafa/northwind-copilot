"""Capture a streamed turn's artifacts and persist conversations/turns.

``TurnRecorder`` observes the same SSE events the client renders and accumulates
them into a storable shape. The chat endpoint drives it as it streams and calls
:func:`persist_turn` in a ``finally`` block, so a turn is saved even if the
client disconnects mid-stream (which also matters for metering later).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from northwind_copilot.tenancy.models import Conversation, Turn


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
    org_id: str,
    user_id: str,
    dataset_id: str | None,
    conversation_id: str | None,
    title_hint: str,
) -> Conversation:
    """Return the caller's conversation, creating one if needed.

    Args:
        session: An open application-database session.
        org_id: The caller's org.
        user_id: The caller's user id.
        dataset_id: The dataset this conversation is about, if any.
        conversation_id: An existing conversation to append to, if provided.
        title_hint: Text (usually the first question) to title a new thread.

    Returns:
        An owned, persisted :class:`Conversation`.

    Raises:
        ValueError: If ``conversation_id`` is given but not owned by the org.
    """
    if conversation_id:
        convo = await session.get(Conversation, conversation_id)
        if convo is None or convo.org_id != org_id:
            raise ValueError("conversation not found")
        return convo
    convo = Conversation(
        org_id=org_id,
        user_id=user_id,
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
) -> Turn:
    """Write one recorded turn to the database."""
    turn = Turn(
        conversation_id=conversation_id,
        question=question,
        answer=recorder.answer,
        queries=recorder.queries,
        charts=recorder.charts,
        insights=recorder.insights,
        error=recorder.error,
        model=recorder.model,
        provider=recorder.provider,
    )
    session.add(turn)
    await session.flush()
    return turn
