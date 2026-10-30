"""Compare fallback candidates on the existing single-turn benchmark.

Run from the repository root: ``uv run python scripts/compare_fallbacks.py``.
Each candidate answers directly, including SQL checker calls, so an unavailable
local primary cannot confound this model comparison. No production defaults,
static graph, prompts, graders, or provider tiers are changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

# Direct script execution otherwise puts scripts/, not the repo, on sys.path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402

from northwind_copilot.eval.graders import grade  # noqa: E402
from northwind_copilot.eval.run_benchmark import (  # noqa: E402
    DATASET,
    extract_answer,
    load_dataset,
)

MODELS = ("gpt-4.1-mini", "gpt-6-luna")
# USD / 1M tokens, Standard short-context, checked 2026-10-30:
# https://developers.openai.com/api/docs/pricing
# Fields: ordinary input, cached input, cache writes (30m), output.
RATES = {
    "gpt-4.1-mini": (0.40, 0.10, 0.40, 1.60),
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
}


def cost_usd(usage: dict, model: str) -> float:
    """Price all reported input/output, including cached reads and writes."""
    details = usage.get("prompt_tokens_details") or {}
    tokens_in = usage["prompt_tokens"]
    tokens_out = usage["completion_tokens"]
    cached = details.get("cached_tokens", 0) or 0
    written = details.get("cache_write_tokens", 0) or 0
    ordinary = tokens_in - cached - written
    if ordinary < 0 or tokens_in > 272_000:
        raise ValueError("Usage is outside the validated short-context rate card")
    rate_in, rate_cached, rate_write, rate_out = RATES[model]
    return (
        ordinary * rate_in
        + cached * rate_cached
        + written * rate_write
        + tokens_out * rate_out
    ) / 1_000_000


def is_tool_failure(output) -> bool:
    """SQL tools return Error: text even when ToolMessage.status is success."""
    return getattr(output, "status", None) == "error" or str(
        getattr(output, "content", output)
    ).lstrip().lower().startswith("error:")


class Measurements(BaseCallbackHandler):
    """Capture nested LLM usage, including the SQL checker's model calls."""

    def __init__(self):
        self.usage: list[dict] = []
        self.missing_usage = 0
        self.model_errors = 0
        self.tool_attempts = 0
        self.tool_failures = 0
        self.invalid_tool_calls = 0

    def on_llm_end(self, response, **_kwargs):
        usage = (response.llm_output or {}).get("token_usage")
        if usage and "prompt_tokens" in usage and "completion_tokens" in usage:
            self.usage.append(usage)
        else:
            self.missing_usage += 1
        for group in response.generations:
            for generation in group:
                self.invalid_tool_calls += len(
                    getattr(generation.message, "invalid_tool_calls", []) or []
                )

    def on_llm_error(self, _error, **_kwargs):
        self.model_errors += 1

    def on_tool_start(self, _serialized, _input_str, **_kwargs):
        self.tool_attempts += 1

    def on_tool_end(self, output, **_kwargs):
        self.tool_failures += int(is_tool_failure(output))

    def on_tool_error(self, _error, **_kwargs):
        self.tool_failures += 1


def build_candidate(model_name: str):
    """Mirror the static fallback's prompt/tools/trim, selecting one model."""
    from langchain.agents import create_agent
    from langchain_community.agent_toolkits import SQLDatabaseToolkit

    from northwind_copilot.core.prompts import SYSTEM_PROMPT
    from northwind_copilot.infra.database import build_database
    from northwind_copilot.infra.docs_tool import search_docs
    from northwind_copilot.query.agent_factory import EngineConfig, build_model
    from northwind_copilot.query.middleware import trim_context

    model = build_model(
        EngineConfig(
            provider="openai", model=model_name, api_key=os.getenv("OPENAI_API_KEY")
        )
    )
    tools = SQLDatabaseToolkit(db=build_database(), llm=model).get_tools()
    return create_agent(
        model=model,
        tools=tools + [search_docs],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=None,
        middleware=[trim_context],
    )


def run_question(agent, record: dict, model: str, repetition: int) -> dict:
    """Grade a fresh conversation and retain failures instead of dropping them."""
    measurements = Measurements()
    messages = []
    error = None
    started = time.perf_counter()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": record["question"]}]},
            config={"recursion_limit": 50, "callbacks": [measurements]},
        )
        messages = result["messages"]
    except (
        Exception
    ) as exc:  # noqa: BLE001 - failed questions remain in the denominator
        # Persist exception types, never credentials or raw provider error bodies.
        error = type(exc).__name__
    latency = time.perf_counter() - started
    answer = extract_answer(messages)
    passed, detail = (
        (False, error) if error else grade(record["grader"], answer, record["expected"])
    )
    tool_messages = [m for m in messages if getattr(m, "type", "") == "tool"]
    failures = (
        measurements.tool_failures
        if error
        else sum(is_tool_failure(m) for m in tool_messages)
    ) + measurements.invalid_tool_calls
    complete_usage = bool(measurements.usage) and not (
        measurements.missing_usage or measurements.model_errors
    )
    cost = (
        sum(cost_usd(u, model) for u in measurements.usage) if complete_usage else None
    )
    return {
        "id": record["id"],
        "model": model,
        "repetition": repetition,
        "passed": passed,
        "detail": detail,
        "latency_s": latency,
        "inference_cost_usd": cost,
        "tool_attempts": max(measurements.tool_attempts, len(tool_messages))
        + measurements.invalid_tool_calls,
        "tool_failures": failures,
        "model_errors": measurements.model_errors,
        "error": error,
        "answer": answer,
        "usage": measurements.usage,
        "missing_usage": measurements.missing_usage,
    }


def percentile(values: list[float], fraction: float) -> float:
    """Linearly interpolated sample percentile (same convention as NumPy)."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(results: list[dict]) -> dict:
    """Aggregate every attempted question, including errors and failed grades."""
    summaries = {}
    for model in MODELS:
        rows = [r for r in results if r["model"] == model]
        if not rows:
            continue
        costs = [r["inference_cost_usd"] for r in rows]
        summaries[model] = {
            "questions": len(rows),
            "passed": sum(r["passed"] for r in rows),
            "accuracy": mean(r["passed"] for r in rows),
            "p50_latency_s": percentile([r["latency_s"] for r in rows], 0.50),
            "p95_latency_s": percentile([r["latency_s"] for r in rows], 0.95),
            "mean_inference_cost_usd": (
                mean(costs) if all(c is not None for c in costs) else None
            ),
            "tool_attempts": sum(r["tool_attempts"] for r in rows),
            "tool_failures": sum(r["tool_failures"] for r in rows),
            "invocation_errors": sum(r["error"] is not None for r in rows),
            "model_errors": sum(r["model_errors"] for r in rows),
        }
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--limit", type=int, help="Smoke run only; not decision evidence"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "eval/results/luna-fallback.json"
    )
    args = parser.parse_args()
    if args.repetitions < 1 or (args.limit is not None and args.limit < 1):
        parser.error("repetitions and limit must be positive")
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY must be configured")
    from northwind_copilot.infra.docs_tool import _get_index

    # Exclude one-time index loading/building from both candidates' timings.
    _get_index()
    agents = {model: build_candidate(model) for model in MODELS}
    records = load_dataset(DATASET)
    if args.limit:
        records = records[: args.limit]
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "repetitions": args.repetitions,
        "rates_usd_per_million": RATES,
        "results": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for repetition in range(1, args.repetitions + 1):
        for index, record in enumerate(records):
            # Alternate AB/BA across questions and repetitions; no cherry-picking.
            order = MODELS if (repetition + index) % 2 else MODELS[::-1]
            for model in order:
                result = run_question(agents[model], record, model, repetition)
                report["results"].append(result)
                report["summary"] = summarize(report["results"])
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(
                    f"R{repetition} {model} {record['id']}: "
                    f"{'PASS' if result['passed'] else 'FAIL'} "
                    f"{result['latency_s']:.2f}s",
                    flush=True,
                )
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
