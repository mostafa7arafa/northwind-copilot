"""Unit tests for the streaming pipeline: pure helpers + the event generator.

The agent itself is faked so no LLM or network is touched; the test drives the
same code path the FastAPI ``/api/chat`` endpoint uses.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, ToolMessage

from northwind_copilot.query.agent_factory import EngineConfig
from northwind_copilot.response import streaming
from northwind_copilot.response.streaming import (
    _iter_with_heartbeat,
    _parse_final,
    _Rail,
    _to_messages,
    stream_chat,
)


class TestToMessages:
    def test_maps_roles(self):
        msgs = _to_messages(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "system", "content": "ignored"},
            ]
        )
        assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage"]


class TestParseFinal:
    def test_extracts_prose_bullets_and_chart(self):
        content = (
            "Revenue rose.\n\n"
            "Insights:\n- up 10%\n- peak in July\n\n"
            '```echarts\n{"series": [1]}\n```'
        )
        out = _parse_final(content)
        assert out["prose"] == "Revenue rose."
        assert out["bullets"] == ["up 10%", "peak in July"]
        assert out["chart"] == {"series": [1]}

    def test_strips_markdown_table_rows(self):
        content = "Here it is:\n| a | b |\n| --- | --- |\n| 1 | 2 |\nDone."
        out = _parse_final(content)
        assert "|" not in out["prose"]
        assert "Done." in out["prose"]

    def test_invalid_echarts_json_ignored(self):
        out = _parse_final("Text\n```echarts\n{not json}\n```")
        assert out["chart"] is None
        assert out["prose"] == "Text"


class TestRail:
    def test_advance_marks_prior_done_and_target_active(self):
        rail = _Rail()
        events = rail.advance_to("execute")
        statuses = {(e["stage"], e["status"]) for e in events}
        assert ("understand", "done") in statuses
        assert ("sql", "done") in statuses
        assert ("execute", "active") in statuses

    def test_finish_is_idempotent(self):
        rail = _Rail()
        assert rail.finish("sql")  # first time emits
        assert rail.finish("sql") == []  # already done


def _drain(aiter_factory):
    """Run an async generator to completion and return the list of items."""

    async def _run():
        out = []
        async for item in aiter_factory():
            out.append(item)
        return out

    return asyncio.run(_run())


class TestHeartbeat:
    def test_emits_ping_when_idle_then_items(self):
        async def src():
            await asyncio.sleep(0.03)
            yield "a"
            yield "b"

        def factory():
            return _iter_with_heartbeat(src(), 0.01)

        items = _drain(factory)
        kinds = [k for k, _ in items]
        assert "ping" in kinds
        assert ("item", "a") in items and ("item", "b") in items


class _FakeAgent:
    def __init__(self, updates, raise_exc=None):
        self._updates = updates
        self._raise = raise_exc

    def astream(self, inp, stream_mode=None, config=None):
        updates, raise_exc = self._updates, self._raise

        async def gen():
            for u in updates:
                yield u
            if raise_exc is not None:
                raise raise_exc

        return gen()


def _collect_stream(monkeypatch, agent):
    monkeypatch.setattr(streaming, "build_agent_for", lambda config, **kw: agent)
    monkeypatch.setattr(
        streaming, "run_sql", lambda sql: {"columns": ["x"], "rows": [[1], [2]]}
    )
    monkeypatch.setattr(streaming, "infer_chart", lambda table: {"series": []})

    async def _run():
        out = []
        async for ev in stream_chat(
            history=[{"role": "user", "content": "revenue?"}],
            config=EngineConfig(provider="ollama", model="m"),
            user_preferences="",
            fallback=None,
            session_id="s1",
        ):
            out.append(ev)
        return out

    return asyncio.run(_run())


class TestStreamChat:
    def test_full_pipeline_events(self, monkeypatch):
        tool_call = {
            "name": "sql_db_query",
            "args": {"query": "SELECT 1 AS x"},
            "id": "1",
            "type": "tool_call",
        }
        updates = [
            {"agent": {"messages": [AIMessage(content="", tool_calls=[tool_call])]}},
            {
                "tools": {
                    "messages": [
                        ToolMessage(
                            content="[(1,)]", name="sql_db_query", tool_call_id="1"
                        )
                    ]
                }
            },
            {
                "agent": {
                    "messages": [
                        AIMessage(content="Revenue is 100.\n\nInsights:\n- up\n- peak")
                    ]
                }
            },
        ]
        events = _collect_stream(monkeypatch, _FakeAgent(updates))
        types = [e["type"] for e in events]
        assert types[0] == "engine"
        for expected in ("sql", "table", "chart", "insights", "final", "done"):
            assert expected in types
        sql_event = next(e for e in events if e["type"] == "sql")
        assert "SELECT 1" in sql_event["sql"]

    def test_agent_error_surfaces_error_event(self, monkeypatch):
        agent = _FakeAgent([], raise_exc=RuntimeError("boom"))
        events = _collect_stream(monkeypatch, agent)
        types = [e["type"] for e in events]
        assert "error" in types
        assert types[-1] == "done"
        err = next(e for e in events if e["type"] == "error")
        assert "boom" in err["detail"]
