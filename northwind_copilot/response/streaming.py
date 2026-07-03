"""Translate the agent's message stream into structured pipeline events.

The frontend renders each assistant turn as a pipeline (Understand -> SQL ->
Execute -> Results -> Chart -> Insights). This module runs the agent and, as
tool calls and messages arrive, yields the events that drive that rail, plus
every executed SQL statement with its result table, the chart specs (a capable
cloud model may draw several), and insights.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from northwind_copilot.core.config import settings
from northwind_copilot.query.agent_factory import (
    DatasetContext,
    EngineConfig,
    build_agent_for,
)
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
    """Split a final answer into prose, insight bullets, and ECharts options.

    A capable cloud model may draw several charts in one turn (one fenced
    ``echarts`` block per view); every valid block is kept, in order.

    Args:
        content: The assistant's final message text.

    Returns:
        ``{"prose", "bullets", "charts"}`` where charts is a list of option
        dicts (empty when the model drew none).
    """
    charts: list[dict[str, Any]] = []
    body = content or ""

    for match in _ECHARTS_RE.finditer(body):
        try:
            charts.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    if _ECHARTS_RE.search(body):
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

    return {"prose": body, "bullets": bullets, "charts": charts}


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
    dataset: DatasetContext | None = None,
) -> AsyncIterator[dict]:
    """Run the agent for one turn and yield structured pipeline events.

    Args:
        history: The conversation so far as ``{"role", "content"}`` dicts.
        config: The chosen engine (provider/model/key).
        user_preferences: Free text appended to the system prompt.
        fallback: Optional escalation model for a local primary.
        session_id: The browser session id. Attached as run metadata so
            LangSmith groups every turn of a conversation into one thread.
        dataset: The uploaded dataset to query (hosted mode). When ``None`` the
            agent runs against the configured Northwind database (POC).

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
        config,
        user_preferences=user_preferences,
        fallback=fallback,
        dataset=dataset,
    )

    captured_queries: list[str] = []  # every distinct query executed, in order
    checker_sql = ""  # from the checker tool (fallback, same `query` arg)
    final_content = ""

    async def emit_artifacts() -> AsyncIterator[dict]:
        """Emit sql/table/chart/insights events from whatever was captured.

        Shared by the success path and the timeout path, so a turn cut short
        by the deadline still shows every query that completed instead of
        discarding the work.
        """
        parsed = _parse_final(final_content)

        # Prefer executed queries; fall back to the checked query if the model
        # produced a final answer without a distinct query tool call.
        if not captured_queries and checker_sql:
            for ev in rail.advance_to("sql"):
                yield ev
            captured_queries.append(checker_sql)
            yield {"type": "sql", "sql": checker_sql, "seq": 0}

        # Re-run every captured query so each gets a structured table, keyed by
        # the same seq as its sql event. A query that errors (or isn't a SELECT)
        # simply yields no table for that seq.
        tables: list[dict[str, Any] | None] = []
        db_path = dataset.sqlite_path if dataset else None
        for seq, query in enumerate(captured_queries):
            table = run_sql(query, db_path)
            tables.append(table)
            if table is not None:
                for ev in rail.advance_to("results"):
                    yield ev
                yield {"type": "table", "seq": seq, **table}

        has_rows = any(t and t["rows"] for t in tables)

        # Only chart real data. If no executed SQL returned rows, suppress any
        # charts the model drew — their values would be fabricated (see the
        # data-integrity rule in northwind_copilot.core.prompts).
        charts: list[dict[str, Any]] = parsed["charts"] if has_rows else []
        inferred = False
        if not charts and has_rows:
            # Local (and chart-less cloud) turns: derive one chart server-side
            # from the last table that has rows.
            last = next((t for t in reversed(tables) if t and t["rows"]), None)
            derived = infer_chart(last) if last else None
            if derived is not None:
                charts = [derived]
                inferred = True
        if charts:
            for ev in rail.advance_to("chart"):
                yield ev
            for seq, chart in enumerate(charts):
                yield {
                    "type": "chart",
                    "option": chart,
                    "inferred": inferred,
                    "seq": seq,
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

    # LangSmith groups runs into a thread when a run carries a `session_id`
    # (or `thread_id`/`conversation_id`) metadata key. Without this, each turn
    # is a standalone trace and the Threads view stays empty.
    run_config = {"metadata": {"session_id": session_id}} if session_id else None

    # Cloud turns get a larger budget: a multi-query, multi-chart analysis
    # legitimately runs past the local cutoff, and the SSE heartbeat keeps the
    # connection warm the whole time. Local keeps the tight budget — a stuck
    # small model should be cut promptly.
    deadline_budget = (
        settings.turn_deadline_seconds
        if config.is_local
        else settings.turn_deadline_seconds_cloud
    )
    deadline = time.monotonic() + deadline_budget

    try:
        stream = agent.astream(
            {"messages": _to_messages(history)},
            stream_mode="updates",
            config=run_config,
        )
        async for kind, update in _iter_with_heartbeat(
            stream.__aiter__(), _HEARTBEAT_SECONDS
        ):
            if time.monotonic() > deadline:
                # Bound one turn's wall-clock so a stuck model (or a runaway
                # tool loop) can't hold a worker and stream forever.
                raise TimeoutError(f"turn exceeded {deadline_budget}s budget")
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
                            query = args.get("query", "")
                            for ev in rail.advance_to("sql"):
                                yield ev
                            # A complex turn may run several queries (one per
                            # view); emit each distinct one so the client can
                            # show every statement, not just the last.
                            if query and query not in captured_queries:
                                captured_queries.append(query)
                                yield {
                                    "type": "sql",
                                    "sql": query,
                                    "seq": len(captured_queries) - 1,
                                }
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

        # ---- assemble the artifacts from what we captured ------------------
        async for ev in emit_artifacts():
            yield ev

        parsed = _parse_final(final_content)
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

    except TimeoutError:
        logger.warning(
            "stream_chat timed out for provider=%s model=%s after %ss",
            config.provider,
            config.model,
            deadline_budget,
        )
        # Salvage rather than discard: the queries that already executed still
        # yield real tables (and possibly an inferred chart), so the user sees
        # the partial analysis alongside the timeout notice.
        async for ev in emit_artifacts():
            yield ev
        yield {
            "type": "error",
            "message": "The analysis hit its time budget and was stopped "
            "early — showing what completed. Try a narrower question or a "
            "faster engine for the rest.",
            "detail": "timeout",
        }

    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        # Log the full traceback server-side with a correlation id, and hand the
        # client only that id — raw exception text can leak connection URIs,
        # file paths, and request fragments on a public deployment.
        error_id = uuid.uuid4().hex[:12]
        logger.exception(
            "stream_chat failed [%s] for provider=%s model=%s: %s",
            error_id,
            config.provider,
            config.model,
            exc,
        )
        yield {
            "type": "error",
            "message": "The query couldn't be completed. Please try again.",
            "detail": f"error_id={error_id}",
        }

    yield {"type": "done"}
