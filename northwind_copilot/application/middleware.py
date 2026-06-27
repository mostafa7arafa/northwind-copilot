"""Agent middleware: context trimming and fallback escalation."""

from __future__ import annotations

from collections.abc import Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    before_model,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import trim_messages

from northwind_copilot.config import settings


@before_model
def trim_context(state, runtime):
    """Trim the message history to the configured token budget.

    Keeps the most recent messages so the re-sent context stays bounded as the
    agent loop grows.

    Args:
        state: The current agent state containing ``messages``.
        runtime: The agent runtime (unused).

    Returns:
        A state update with the trimmed message list.
    """
    trimmed = trim_messages(
        state["messages"],
        token_counter="approximate",
        max_tokens=settings.max_context_tokens,
        strategy="last",
    )
    return {"messages": trimmed}


def is_degenerate(response: ModelResponse) -> bool:
    """Return whether a model response is unusable — no text and no tool call.

    The local model sometimes returns an empty completion on the hardest
    reasoning steps. The agent loop reads that as "done" and stops, so the
    failure is silent. Treating it as degenerate lets us escalate instead.

    Args:
        response: The response produced by a model call.

    Returns:
        ``True`` if the final message has neither text content nor tool calls.
    """
    messages = getattr(response, "result", None) or []
    if not messages:
        return True
    last = messages[-1]
    has_text = bool(str(getattr(last, "content", "") or "").strip())
    has_tool_calls = bool(getattr(last, "tool_calls", None))
    return not (has_text or has_tool_calls)


class EscalateToFallbackMiddleware(AgentMiddleware):
    """Escalate a model call to fallback models on an error OR an empty response.

    ``ModelFallbackMiddleware`` only retries on exceptions, so a local model that
    silently returns nothing slips through. This middleware also escalates when
    the primary produces a degenerate response, returning the first usable
    result from the fallback chain.
    """

    def __init__(self, *fallback_models: BaseChatModel) -> None:
        """Initialise the middleware.

        Args:
            *fallback_models: Models to try, in order, after the primary fails
                or returns nothing usable.
        """
        super().__init__()
        self.fallbacks = list(fallback_models)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Run the primary model, escalating to fallbacks when needed.

        Args:
            request: The model request to execute.
            handler: Callback that runs a request against its model.

        Returns:
            The first usable response. If every model fails or is degenerate,
            the last response is returned (or the last exception re-raised when
            no response was produced at all).

        Raises:
            Exception: The last exception, if no model produced any response.
        """
        last_response: ModelResponse | None = None
        last_exc: Exception | None = None

        try:
            response = handler(request)
            if not is_degenerate(response):
                return response
            last_response = response  # usable-looking but empty; try fallbacks
        except Exception as exc:  # noqa: BLE001 - escalate, then re-raise if all fail
            last_exc = exc

        for model in self.fallbacks:
            try:
                response = handler(request.override(model=model))
                if not is_degenerate(response):
                    return response
                last_response = response
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

        if last_response is not None:
            return last_response
        raise last_exc  # type: ignore[misc]
