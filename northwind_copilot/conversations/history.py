"""Rebuild agent prompt history from stored turns.

This is the server-side twin of the frontend's old ``turnMemory`` /
``HISTORY_WINDOW`` logic: given a conversation's persisted turns, produce the
``{role, content}`` message list the agent replays. Because the server owns
this, the client can send only the new question — it can no longer fabricate an
assistant "memory" to smuggle content into the prompt.
"""

from __future__ import annotations

from typing import Any

# How many prior turns to replay. Cloud engines have room for a richer window;
# the server-side trim middleware bounds the final payload regardless.
_HISTORY_WINDOW = 5
_TABLE_PREVIEW_ROWS = 3


def _compact_table(table: dict[str, Any]) -> str:
    """Render a few rows of a result table as a compact text recap."""
    columns = table.get("columns", [])
    rows = table.get("rows", [])
    head = " | ".join(str(c) for c in columns)
    preview = [
        " | ".join("" if c is None else str(c) for c in row)
        for row in rows[:_TABLE_PREVIEW_ROWS]
    ]
    more = f"\n… ({len(rows)} rows total)" if len(rows) > _TABLE_PREVIEW_ROWS else ""
    return f"Result ({len(rows)} rows):\n{head}\n" + "\n".join(preview) + more


def _turn_memory(turn: Any) -> str:
    """Build the assistant-side recap for one prior turn.

    Includes the prose answer plus each executed query and a preview of its
    result, so a follow-up ("break that down by month") has a real anchor.
    """
    parts: list[str] = []
    if turn.answer:
        parts.append(turn.answer)
    for q in (turn.queries or [])[:3]:
        sql = q.get("sql")
        table = q.get("table")
        if sql:
            parts.append("SQL used:\n```sql\n" + sql + "\n```")
        if table and table.get("rows"):
            parts.append(_compact_table(table))
    return "\n\n".join(parts)


def build_history(turns: list[Any], question: str) -> list[dict[str, str]]:
    """Assemble the replay history for a new question.

    Args:
        turns: The conversation's prior turns, oldest first.
        question: The new user question for this turn.

    Returns:
        A list of ``{"role", "content"}`` messages ending with ``question``.
    """
    history: list[dict[str, str]] = []
    for turn in turns[-_HISTORY_WINDOW:]:
        history.append({"role": "user", "content": turn.question})
        memory = _turn_memory(turn)
        if memory:
            history.append({"role": "assistant", "content": memory})
    history.append({"role": "user", "content": question})
    return history
