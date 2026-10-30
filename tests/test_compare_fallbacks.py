"""Offline checks for fallback-comparison accounting; no provider calls."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from scripts.compare_fallbacks import (
    Measurements,
    cost_usd,
    is_tool_failure,
    percentile,
    run_question,
    summarize,
)


def llm_result(usage=None, message=None):
    return LLMResult(
        generations=[[ChatGeneration(message=message or AIMessage(content="5"))]],
        llm_output={"token_usage": usage} if usage else {},
    )


def test_cost_counts_cached_reads_and_writes_without_double_counting():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 100},
    }
    assert cost_usd(usage, "gpt-6-luna") == pytest.approx(0.0001345)


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 272001, "completion_tokens": 1},
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    ],
)
def test_cost_rejects_usage_outside_the_rate_card(usage):
    with pytest.raises(ValueError):
        cost_usd(usage, "gpt-6-luna")


@pytest.mark.parametrize(
    "output,expected",
    [
        ("Error: invalid SQL", True),
        (ToolMessage(content="Bad input", tool_call_id="a", status="error"), True),
        (ToolMessage(content="Error: invalid SQL", tool_call_id="a"), True),
        ("[(0,)]", False),
    ],
)
def test_tool_error_classification(output, expected):
    assert is_tool_failure(output) is expected


def test_nested_llm_calls_and_invalid_tool_calls_are_captured():
    measurements = Measurements()
    usage = {"prompt_tokens": 100, "completion_tokens": 10}
    measurements.on_llm_end(llm_result(usage))
    measurements.on_llm_end(llm_result(usage))  # SQL checker, not just agent messages
    invalid = AIMessage(
        content="",
        invalid_tool_calls=[{"name": "bad", "args": "{", "id": "bad-call"}],
    )
    measurements.on_llm_end(llm_result(usage, invalid))
    assert len(measurements.usage) == 3
    assert measurements.invalid_tool_calls == 1


def test_run_question_accounts_for_checker_usage_and_unknown_tool_errors():
    usage = {"prompt_tokens": 100, "completion_tokens": 10}

    class Agent:
        def invoke(self, _inputs, config):
            callback = config["callbacks"][0]
            callback.on_llm_end(llm_result(usage))
            callback.on_llm_end(llm_result(usage))  # nested checker call
            # Unknown tools may return an error without any tool-start callback.
            return {
                "messages": [
                    ToolMessage(
                        content="Unknown tool", tool_call_id="x", status="error"
                    ),
                    AIMessage(content="5"),
                ]
            }

    result = run_question(
        Agent(),
        {"id": "count", "question": "Count?", "grader": "numeric", "expected": 5},
        "gpt-4.1-mini",
        1,
    )
    assert result["passed"]
    assert result["tool_failures"] == 1
    assert result["tool_attempts"] == 1
    assert result["inference_cost_usd"] == pytest.approx(2 * 0.000056)


def test_aborted_question_keeps_failure_and_redacts_exception_message():
    class Agent:
        def invoke(self, _inputs, config):
            callback = config["callbacks"][0]
            callback.on_tool_start({}, "")
            callback.on_tool_error(RuntimeError("private error body"))
            raise RuntimeError("private error body")

    result = run_question(
        Agent(),
        {"id": "count", "question": "Count?", "grader": "numeric", "expected": 5},
        "gpt-4.1-mini",
        1,
    )
    assert not result["passed"]
    assert result["tool_failures"] == 1
    assert result["error"] == "RuntimeError"
    assert "private" not in str(result)
    assert result["inference_cost_usd"] is None


def test_missing_usage_is_not_reported_as_free():
    measurements = Measurements()
    measurements.on_llm_end(llm_result())
    assert measurements.missing_usage == 1
    assert measurements.usage == []


def test_model_error_is_captured():
    measurements = Measurements()
    measurements.on_llm_error(RuntimeError("failed"))
    assert measurements.model_errors == 1


def test_percentiles_use_linear_interpolation():
    assert percentile([4, 1, 3, 2], 0.50) == 2.5
    assert percentile([4, 1, 3, 2], 0.95) == pytest.approx(3.85)


def test_summary_retains_failed_questions_and_unknown_cost():
    common = dict(
        model="gpt-4.1-mini",
        tool_attempts=2,
        tool_failures=1,
        model_errors=0,
    )
    rows = [
        dict(common, passed=True, latency_s=1.0, inference_cost_usd=0.01, error=None),
        dict(
            common, passed=False, latency_s=3.0, inference_cost_usd=None, error="Error"
        ),
    ]
    summary = summarize(rows)["gpt-4.1-mini"]
    assert summary["accuracy"] == 0.5
    assert summary["questions"] == 2
    assert summary["p50_latency_s"] == 2.0
    assert summary["mean_inference_cost_usd"] is None
    assert summary["invocation_errors"] == 1
    assert summary["tool_failures"] == 2
