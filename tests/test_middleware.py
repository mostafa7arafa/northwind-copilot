"""Unit tests for agent middleware (degenerate detection + fallback escalation).

These tests use lightweight fakes so no real LLM is invoked.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from northwind_copilot.query.middleware import (
    EscalateToFallbackMiddleware,
    is_degenerate,
    make_trim_context,
    trim_context,
)


class FakeResponse:
    """Stand-in for a ModelResponse, exposing only ``.result``."""

    def __init__(self, messages):
        self.result = messages


class FakeRequest:
    """Stand-in for a ModelRequest that records the model in use."""

    def __init__(self, model="primary"):
        self.model = model

    def override(self, model):
        return FakeRequest(model=model)


def _ai(content="", tool_calls=None):
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _tool_call_msg():
    return AIMessage(
        content="",
        tool_calls=[{"name": "sql", "args": {}, "id": "1", "type": "tool_call"}],
    )


class TestIsDegenerate:
    def test_empty_result_is_degenerate(self):
        assert is_degenerate(FakeResponse([]))

    def test_empty_message_is_degenerate(self):
        assert is_degenerate(FakeResponse([_ai(content="")]))

    def test_text_is_not_degenerate(self):
        assert not is_degenerate(FakeResponse([_ai(content="here is the answer")]))

    def test_tool_call_is_not_degenerate(self):
        assert not is_degenerate(FakeResponse([_tool_call_msg()]))


class TestEscalation:
    def _run(self, behaviors, *fallbacks):
        mw = EscalateToFallbackMiddleware(*fallbacks)

        def handler(req):
            return behaviors[req.model]()

        return mw.wrap_model_call(FakeRequest(), handler)

    def test_primary_success_no_escalation(self):
        calls = {"n": 0}

        def primary():
            calls["n"] += 1
            return FakeResponse([_ai("ok")])

        out = self._run({"primary": primary}, "fb")
        assert out.result[-1].content == "ok"
        assert calls["n"] == 1  # fallback never touched

    def test_empty_primary_escalates_to_fallback(self):
        behaviors = {
            "primary": lambda: FakeResponse([_ai("")]),
            "fb": lambda: FakeResponse([_ai("rescued")]),
        }
        out = self._run(behaviors, "fb")
        assert out.result[-1].content == "rescued"

    def test_exception_primary_escalates_to_fallback(self):
        def boom():
            raise RuntimeError("primary down")

        behaviors = {"primary": boom, "fb": lambda: FakeResponse([_ai("rescued")])}
        out = self._run(behaviors, "fb")
        assert out.result[-1].content == "rescued"

    def test_all_degenerate_returns_last_response(self):
        behaviors = {
            "primary": lambda: FakeResponse([_ai("")]),
            "fb": lambda: FakeResponse([_ai("")]),
        }
        out = self._run(behaviors, "fb")
        assert is_degenerate(out)

    def test_all_raise_reraises_last(self):
        def boom():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            self._run({"primary": boom, "fb": boom}, "fb")


class TestAsyncEscalation:
    def _run(self, behaviors, *fallbacks):
        mw = EscalateToFallbackMiddleware(*fallbacks)

        async def handler(req):
            return behaviors[req.model]()

        return asyncio.run(mw.awrap_model_call(FakeRequest(), handler))

    def test_async_primary_success(self):
        out = self._run({"primary": lambda: FakeResponse([_ai("ok")])}, "fb")
        assert out.result[-1].content == "ok"

    def test_async_empty_primary_escalates(self):
        behaviors = {
            "primary": lambda: FakeResponse([_ai("")]),
            "fb": lambda: FakeResponse([_ai("rescued")]),
        }
        assert self._run(behaviors, "fb").result[-1].content == "rescued"

    def test_async_all_raise_reraises(self):
        def boom():
            raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            self._run({"primary": boom, "fb": boom}, "fb")


class TestTrimContext:
    def test_make_trim_context_trims_to_budget(self):
        mw = make_trim_context(40)
        state = {"messages": [_ai("word " * 40) for _ in range(6)]}
        out = mw.before_model(state, None)
        assert "messages" in out
        assert len(out["messages"]) <= len(state["messages"])

    def test_module_default_instance_exists(self):
        assert hasattr(trim_context, "before_model")
