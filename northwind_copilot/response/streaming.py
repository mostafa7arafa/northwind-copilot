"""Translate the agent's message stream into structured pipeline events.

The frontend renders each assistant turn as a pipeline (Understand -> SQL ->
Execute -> Results -> Chart -> Insights). This module runs the agent and, as
tool calls and messages arrive, yields the events that drive that rail, plus the
final SQL, result table, chart spec, and insights.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from northwind_copilot.query.agent_factory import EngineConfig, build_agent_for
from northwind_copilot.response.charting import infer_chart, run_sql

logger = logging.getLogger(__name__)

STAGES = ["understand", "sql", "execute", "results", "chart", "insights"]

_QUERY_TOOL = "sql_db_query"
_CHECKER_TOOL = "sql_db_query_checker"

_ECHARTS_RE = re.compile(r"```echarts\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_INSIGHTS_RE = re.compile(r"insights:\s*(.+)$", re.IGNORECASE | re.DOTALL)
# A Markdown table row is a line whose stripped form starts with a pipe. The
# interface renders the real result set itself, so any table the model draws in
# prose is a duplicate that shows as raw pipes/dashes — drop those lines.
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*$", re.MULTILINE)

# How long the agent may go silent before we emit a keepalive. A slow local
# model can spend tens of seconds generating its first tool call, during which
# no SSE bytes flow; the Next.js dev proxy (and some browsers) drop an idle
# stream in that gap, which surfaces server-side as a CancelledError. A
# heartbeat well under any such timeout keeps the connection warm.
_HEARTBEAT_SECONDS = 10.0


async def _iter_with_heartbeat(
    aiter: AsyncIterator[Any], interval: float
) -> AsyncIterator[tuple[str, Any]]:
    """Iterate ``aiter``, injecting a ping sentinel whenever it stays idle.

    The in-flight ``__anext__`` is held in a persistent task so a heartbeat tick
    never cancels the current step (the slow model generation itself) — we only
    *observe* it with a timeout rather than awaiting it directly.

    Args:
        aiter: The source async iterator (the agent's update stream).
        interval: Seconds of silence after which to emit a ping.

    Yields:
        ``("item", value)`` for each real update, or ``("ping", None)`` when the
        source produced nothing within ``interval`` seconds.
    """
    pending: asyncio.Task = asyncio.ensure_future(aiter.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield "ping", None
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            pending = asyncio.ensure_future(aiter.__anext__())
            yield "item", item
    finally:
        if not pending.done():
            pending.cancel()


def _to_messages(history: list[dict]) -> list[BaseMessage]:
    """Convert wire history into LangChain messages (system is set separately)."""
    out: list[BaseMessage] = []
    for m in history:
        role, content = m.get("role"), m.get("content", "")
        if role == "user":
            out.append(HumanMessage(content))
        elif role == "assistant":
            out.append(AIMessage(content))
    return out


def _parse_final(content: str) -> dict[str, Any]:
    """Split a final answer into prose, insight bullets, and an ECharts option.

    Args:
        content: The assistant's final message text.

    Returns:
        ``{"prose", "bullets", "chart"}`` where chart is an option dict or None.
    """
    chart: dict[str, Any] | None = None
    body = content or ""

    match = _ECHARTS_RE.search(body)
    if match:
        try:
            chart = json.loads(match.group(1))
        except json.JSONDecodeError:
            chart = None
        body = _ECHARTS_RE.sub("", body).strip()

    bullets: list[str] = []
    ins = _INSIGHTS_RE.search(body)
    if ins:
        for line in ins.group(1).splitlines():
            line = line.strip()
            if line.startswith(("-", "•", "*")):
                bullets.append(line.lstrip("-•* ").strip())
        body = body[: ins.start()].strip()

    # Drop any Markdown table the model drew in prose — the UI renders the real
    # result set, so this would just duplicate it as raw pipes/dashes. Collapse
    # the blank lines the removal leaves behind.
    body = _MD_TABLE_ROW_RE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return {"prose": body, "bullets": bullets, "chart": chart}


class _Rail:
    """Tracks pipeline progress and yields stage transition events."""

    def __init__(self) -> None:
        self._done: set[str] = set()
        self._active: str | None = None

    def advance_to(self, target: str) -> list[dict]:
        """Mark stages up to ``target`` done and ``target`` active.

        Args:
            target: The stage now in progress.

        Returns:
            The stage events to emit for this transition.
        """
        events: list[dict] = []
        target_i = STAGES.index(target)
        for stage in STAGES[:target_i]:
            if stage not in self._done:
                self._done.add(stage)
                events.append({"type": "stage", "stage": stage, "status": "done"})
        if self._active != target and target not in self._done:
            self._active = target
            events.append({"type": "stage", "stage": target, "status": "active"})
        return events

    def finish(self, stage: str) -> list[dict]:
        """Mark a single stage done."""
        if stage in self._done:
            return []
        self._done.add(stage)
        return [{"type": "stage", "stage": stage, "status": "done"}]


async def stream_chat(
    *,
    history: list[dict],
    config: EngineConfig,
    user_preferences: str,
    fallback: Any | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict]:
    """Run the agent for one turn and yield structured pipeline events.

    Args:
        history: The conversation so far as ``{"role", "content"}`` dicts.
        config: The chosen engine (provider/model/key).
        user_preferences: Free text appended to the system prompt.
        fallback: Optional escalation model for a local primary.
        session_id: The browser session id. Attached as run metadata so
            LangSmith groups every turn of a conversation into one thread.

    Yields:
        Event dicts: ``engine``, ``stage``, ``sql``, ``table``, ``chart``,
        ``insights``, ``final``, ``error``, and finally ``done``.
    """
    yield {
        "type": "engine",
        "engine": "local" if config.is_local else "cloud",
        "provider": config.provider,
        "model": config.model,
    }

    rail = _Rail()
    for ev in rail.advance_to("understand"):
        yield ev

    agent = build_agent_for(
        config, user_preferences=user_preferences, fallback=fallback
    )

    captured_sql = ""  # from the query tool (authoritative)
    checker_sql = ""  # from the checker tool (fallback, same `query` arg)
    sql_emitted = False
    final_content = ""

    # LangSmith groups runs into a thread when a run carries a `session_id`
    # (or `thread_id`/`conversation_id`) metadata key. Without this, each turn
    # is a standalone trace and the Threads view stays empty.
    run_config = {"metadata": {"session_id": session_id}} if session_id else None

    try:
        stream = agent.astream(
            {"messages": _to_messages(history)},
            stream_mode="updates",
            config=run_config,
        )
        async for kind, update in _iter_with_heartbeat(
            stream.__aiter__(), _HEARTBEAT_SECONDS
        ):
            if kind == "ping":
                # Keeps the SSE socket warm while the model thinks; the client
                # has no handler for this type, so it's a harmless no-op there.
                yield {"type": "ping"}
                continue
            for node_state in update.values():
                if not isinstance(node_state, dict):
                    continue
                for msg in node_state.get("messages", []):
                    tool_calls = getattr(msg, "tool_calls", None) or []
                    for call in tool_calls:
                        name = call.get("name", "")
                        args = call.get("args", {}) or {}
                        if name == _CHECKER_TOOL:
                            checker_sql = args.get("query", checker_sql)
                            for ev in rail.advance_to("sql"):
                                yield ev
                        elif name == _QUERY_TOOL:
                            captured_sql = args.get("query", captured_sql)
                            for ev in rail.advance_to("sql"):
                                yield ev
                            if captured_sql and not sql_emitted:
                                sql_emitted = True
                                yield {"type": "sql", "sql": captured_sql}
                            for ev in rail.advance_to("execute"):
                                yield ev

                    # A ToolMessage from the query tool means execution finished.
                    if getattr(msg, "type", "") == "tool" and (
                        getattr(msg, "name", "") == _QUERY_TOOL
                    ):
                        for ev in rail.advance_to("results"):
                            yield ev

                    # Final assistant message: content, no pending tool calls.
                    if (
                        isinstance(msg, AIMessage)
                        and not tool_calls
                        and str(getattr(msg, "content", "") or "").strip()
                    ):
                        final_content = str(msg.content)

        # ---- assemble the artifact from what we captured -------------------
        parsed = _parse_final(final_content)

        # Prefer the executed query; fall back to the checked query if the model
        # produced a final answer without a distinct query tool call.
        final_sql = captured_sql or checker_sql
        if final_sql and not sql_emitted:
            for ev in rail.advance_to("sql"):
                yield ev
            yield {"type": "sql", "sql": final_sql}

        table = run_sql(final_sql)
        has_rows = bool(table and table["rows"])
        if table is not None:
            for ev in rail.advance_to("results"):
                yield ev
            yield {"type": "table", **table}

        # Only chart real data. If the executed SQL returned no rows, suppress any
        # chart the model drew — its values would be fabricated (see the
        # data-integrity rule in northwind_copilot.core.prompts).
        chart = (parsed["chart"] or infer_chart(table)) if has_rows else None
        if chart is not None:
            for ev in rail.advance_to("chart"):
                yield ev
            yield {
                "type": "chart",
                "option": chart,
                "inferred": bool(parsed["chart"] is None),
            }
            for ev in rail.finish("chart"):
                yield ev

        if parsed["prose"] or parsed["bullets"]:
            for ev in rail.advance_to("insights"):
                yield ev
            yield {
                "type": "insights",
                "text": parsed["prose"],
                "bullets": parsed["bullets"],
            }
            for ev in rail.finish("insights"):
                yield ev

        yield {"type": "final", "text": parsed["prose"] or final_content}

    except asyncio.CancelledError:
        # The client closed the SSE connection mid-stream (tab refresh, a
        # frontend hot-reload, or a new request superseding this one). This is
        # not an agent failure — log one clean line and re-raise, since a
        # CancelledError must never be swallowed.
        logger.info(
            "stream_chat cancelled (client disconnected) for provider=%s model=%s",
            config.provider,
            config.model,
        )
        raise

    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        # Log the full traceback server-side: the generic client message and the
        # SSE `detail` field are easy to miss, and upstream (e.g. OpenAI) errors
        # raised mid-stream may never reach LangSmith.
        logger.exception(
            "stream_chat failed for provider=%s model=%s: %s",
            config.provider,
            config.model,
            exc,
        )
        yield {
            "type": "error",
            "message": "The query couldn't be completed.",
            "detail": str(exc),
        }

    yield {"type": "done"}
