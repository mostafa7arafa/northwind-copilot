"""Accumulate per-turn token usage from the agent's message stream.

``UsageAccumulator`` is handed to ``response.streaming.stream_chat`` (as an
optional, defaulted parameter so the POC path is untouched) and observes every
``AIMessage`` in the update loop. LangChain normalises provider token counts
onto ``AIMessage.usage_metadata`` for OpenAI-compatible backends and Ollama
alike, so one accumulator covers every engine.
"""

from __future__ import annotations

from typing import Any


class UsageAccumulator:
    """Sum token usage across every model call of one analyst turn.

    A single turn is several model invocations (tool-calling loop, query
    checker, final answer); each surfaces as its own ``AIMessage``. Messages
    are de-duplicated by id because a graph update can replay state that
    contains messages already seen.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self._seen: set[str] = set()

    def observe(self, message: Any) -> None:
        """Fold one message's ``usage_metadata`` into the running totals.

        Args:
            message: Any streamed message; non-AI messages and messages without
                usage metadata are ignored.
        """
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            return
        msg_id = getattr(message, "id", None)
        if msg_id is not None:
            if msg_id in self._seen:
                return
            self._seen.add(msg_id)
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        """Total tokens observed so far."""
        return self.input_tokens + self.output_tokens

    @property
    def has_usage(self) -> bool:
        """Whether any token usage was observed this turn."""
        return self.total_tokens > 0
