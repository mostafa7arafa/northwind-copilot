"""Run one arm (local or cloud) of the multi-turn experiment against LangSmith.

Each dataset example is a 3-turn conversation. The target replays the turns
against a real agent, carrying message history forward, and records per-turn
answers, the tool output the agent actually saw, latency, and token counts.
Three LLM judges plus non-LLM latency/token scorers then write feedback to a
LangSmith experiment on the ``northwind-multiturn-analyst`` dataset.

Fairness notes, all deliberate:

* The local arm runs with ``fallback=None``. ``build_agent_for`` would otherwise
  attach ``EscalateToFallbackMiddleware``, and a failed local turn would be
  silently answered by the cloud model — the arm would measure a hybrid.
* Each arm uses the prompt the product actually gives it (lean for local, full
  analyst prompt for cloud). We compare the two *engines as shipped*, not the
  same prompt on two models.
* Cloud answers may carry ```echarts blocks, which local answers never do. They
  are stripped before judging so the judge scores prose against prose.

Usage:
    python -m northwind_copilot.eval.multiturn.run_experiment --arm local
    python -m northwind_copilot.eval.multiturn.run_experiment --arm cloud
    python -m northwind_copilot.eval.multiturn.run_experiment --arm both --limit 2
"""

from __future__ import annotations

# Use the OS certificate store (which trusts this network's TLS-intercepting
# root CA) rather than certifi. Must run before anything opens a TLS socket.
import truststore

truststore.inject_into_ssl()

import argparse  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from statistics import mean  # noqa: E402
from typing import Any  # noqa: E402

from langchain_core.messages import HumanMessage  # noqa: E402
from langsmith import Client, evaluate  # noqa: E402

from northwind_copilot.core.config import settings  # noqa: E402
from northwind_copilot.eval.multiturn.build_dataset import DATASET_NAME  # noqa: E402
from northwind_copilot.eval.multiturn.judges import (  # noqa: E402
    JUDGE_MODEL,
    context_retention_judge,
    correctness_judge,
    hallucination_judge,
    judge_with_retry,
)
from northwind_copilot.query.agent_factory import (  # noqa: E402
    EngineConfig,
    build_agent_for,
)

CLOUD_MODEL = "gpt-4.1-mini"
RECURSION_LIMIT = 30

_ECHARTS_BLOCK = re.compile(r"```echarts.*?```", re.DOTALL)


def _strip_charts(text: str) -> str:
    """Remove ```echarts fenced blocks so prose is judged against prose."""
    return _ECHARTS_BLOCK.sub("", text).strip()


def _text_of(content: Any) -> str:
    """Flatten a message content field to plain text."""
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        ).strip()
    return str(content or "").strip()


def _truncate(text: str, limit: int = 2000) -> str:
    """Cap a tool result so a schema dump cannot dominate the judge's prompt."""
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def _format_call(call: dict) -> str:
    """Render a tool call as ``name(arg=value)`` for the grounding context."""
    args = call.get("args") or {}
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{call.get('name', 'tool')}({rendered})"


def build_arm(arm: str):
    """Construct the agent for one arm.

    Args:
        arm: ``"local"`` or ``"cloud"``.

    Returns:
        A ``(compiled_agent, model_label)`` pair.

    Raises:
        RuntimeError: If the cloud arm is requested without ``OPENAI_API_KEY``.
        ValueError: If ``arm`` is not recognised.
    """
    if arm == "local":
        config = EngineConfig(provider="ollama", model=settings.primary_model)
        # fallback=None: no silent cloud rescue. See module docstring.
        return build_agent_for(config, fallback=None), settings.primary_model
    if arm == "cloud":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is required for the cloud arm.")
        config = EngineConfig(provider="openai", model=CLOUD_MODEL, api_key=key)
        return build_agent_for(config, fallback=None), CLOUD_MODEL
    raise ValueError(f"Unknown arm: {arm!r}")


def run_conversation(agent, questions: list[str]) -> dict[str, Any]:
    """Replay a scripted conversation, capturing what the agent saw and said.

    Message history is carried forward across turns, so turn 3 can only resolve
    "that product" if the agent genuinely retained turn 1.

    Args:
        agent: The compiled LangGraph agent.
        questions: The scripted user turns, in order.

    Returns:
        A record with one entry per turn plus conversation-level aggregates.
    """
    history: list = []
    turns: list[dict[str, Any]] = []
    # Grounding evidence accumulates: a turn-3 answer may legitimately name an
    # entity that a turn-1 query retrieved.
    evidence: list[str] = []

    for position, question in enumerate(questions, 1):
        history = history + [HumanMessage(content=question)]
        before = len(history)

        started = time.perf_counter()
        error = None
        try:
            result = agent.invoke(
                {"messages": history},
                config={"recursion_limit": RECURSION_LIMIT},
            )
            history = result["messages"]
        except Exception as exc:  # noqa: BLE001 - a crashed turn is a data point
            error = f"{type(exc).__name__}: {exc}"
        latency = time.perf_counter() - started

        produced = history[before:]
        answer = ""
        tool_outputs: list[str] = []
        pending: dict[str, str] = {}
        tokens_in = tokens_out = model_calls = 0

        for msg in produced:
            kind = getattr(msg, "type", "")
            if kind == "ai":
                model_calls += 1
                usage = getattr(msg, "usage_metadata", None) or {}
                tokens_in += usage.get("input_tokens", 0) or 0
                tokens_out += usage.get("output_tokens", 0) or 0
                for call in getattr(msg, "tool_calls", None) or []:
                    pending[call["id"]] = _format_call(call)
                text = _text_of(msg.content)
                if text:
                    answer = text
            elif kind == "tool":
                # The grounding evidence is the CALL plus its result. The row
                # "revenue=4590093.58" alone cannot justify the claim "in 2017";
                # only the query's WHERE clause can. Dropping the arguments makes
                # every grounded answer look fabricated to the judge.
                call = pending.pop(getattr(msg, "tool_call_id", ""), msg.name)
                tool_outputs.append(f"{call}\n  -> {_truncate(_text_of(msg.content))}")

        evidence.extend(f"[turn {position}] {line}" for line in tool_outputs)

        turns.append(
            {
                "position": position,
                "question": question,
                "answer": _strip_charts(answer),
                "context": "\n".join(evidence) or "(the agent ran no tools)",
                "latency_s": round(latency, 2),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "model_calls": model_calls,
                "error": error,
            }
        )

    return {
        "turns": turns,
        "transcript": "\n\n".join(
            f"User (turn {t['position']}): {t['question']}\n"
            f"Agent (turn {t['position']}): {t['answer'] or '(no answer)'}"
            for t in turns
        ),
        "total_latency_s": round(sum(t["latency_s"] for t in turns), 2),
        "total_tokens_in": sum(t["tokens_in"] for t in turns),
        "total_tokens_out": sum(t["tokens_out"] for t in turns),
        "total_model_calls": sum(t["model_calls"] for t in turns),
        "errors": [t["error"] for t in turns if t["error"]],
    }


# --------------------------------------------------------------------------
# Evaluators. Each returns LangSmith feedback; higher is always better.
# --------------------------------------------------------------------------


def _as_score(verdict: dict) -> float:
    """Coerce an openevals verdict to a float score."""
    score = verdict.get("score")
    if isinstance(score, bool):
        return 1.0 if score else 0.0
    return float(score or 0.0)


def correctness_evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """Score each turn's answer against its computed ground truth."""
    results = []
    scores = []
    failures = 0
    turns = outputs["turns"]
    refs = {r["position"]: r["reference"] for r in reference_outputs["turns"]}

    for turn in turns:
        # Later turns are meaningless without the conversation that precedes
        # them ("And the worst?"), so the judge sees the prior turns too.
        prior = "\n".join(
            f"Turn {t['position']}: {t['question']} -> {t['answer']}"
            for t in turns
            if t["position"] < turn["position"]
        )
        question = (
            f"Conversation so far:\n{prior}\n\nCurrent question: {turn['question']}"
            if prior
            else turn["question"]
        )
        verdict = judge_with_retry(
            correctness_judge,
            inputs=question,
            outputs=turn["answer"] or "(the agent produced no answer)",
            reference_outputs=refs[turn["position"]],
        )
        if verdict is None:
            failures += 1
            continue
        score = _as_score(verdict)
        scores.append(score)
        results.append(
            {
                "key": f"correctness_t{turn['position']}",
                "score": score,
                "comment": verdict.get("comment", ""),
            }
        )

    if scores:
        results.append({"key": "correctness", "score": mean(scores)})
    results.append({"key": "judge_failures", "score": failures})
    return {"results": results}


def hallucination_evaluator(inputs: dict, outputs: dict) -> dict:
    """Score whether each answer is grounded in the tool output it obtained.

    No reference is passed: grounding is about provenance, not correctness. A
    wrong number copied faithfully from a wrong query is grounded but incorrect,
    and the correctness judge is what catches it.
    """
    results = []
    scores = []

    for turn in outputs["turns"]:
        verdict = judge_with_retry(
            hallucination_judge,
            inputs=turn["question"],
            outputs=turn["answer"] or "(the agent produced no answer)",
            context=turn["context"],
        )
        if verdict is None:
            continue
        score = _as_score(verdict)
        scores.append(score)
        results.append(
            {
                "key": f"no_hallucination_t{turn['position']}",
                "score": score,
                "comment": verdict.get("comment", ""),
            }
        )

    if scores:
        results.append({"key": "no_hallucination", "score": mean(scores)})
    return {"results": results}


def context_retention_evaluator(
    inputs: dict, outputs: dict, reference_outputs: dict
) -> dict:
    """Score anaphora resolution across the whole conversation."""
    references = "\n".join(
        f"Turn {r['position']}: {r['reference']}" for r in reference_outputs["turns"]
    )
    questions = "\n".join(
        f"Turn {i}: {q}" for i, q in enumerate(inputs["questions"], 1)
    )
    verdict = judge_with_retry(
        context_retention_judge,
        inputs=questions,
        outputs=outputs["transcript"],
        reference_outputs=references,
    )
    if verdict is None:
        return {"results": []}
    return {
        "results": [
            {
                "key": "context_retention",
                "score": _as_score(verdict),
                "comment": verdict.get("comment", ""),
            }
        ]
    }


def efficiency_evaluator(inputs: dict, outputs: dict) -> dict:
    """Record latency, tokens, and tool round-trips. No LLM involved."""
    turns = outputs["turns"]
    return {
        "results": [
            {"key": "latency_s_total", "score": outputs["total_latency_s"]},
            {
                "key": "latency_s_per_turn",
                "score": round(mean(t["latency_s"] for t in turns), 2),
            },
            {"key": "tokens_in", "score": outputs["total_tokens_in"]},
            {"key": "tokens_out", "score": outputs["total_tokens_out"]},
            {"key": "model_calls", "score": outputs["total_model_calls"]},
            {"key": "turn_errors", "score": len(outputs["errors"])},
        ]
    }


def run_arm(arm: str, limit: int | None, concurrency: int) -> None:
    """Run one arm end to end and report the experiment URL."""
    agent, model_label = build_arm(arm)
    client = Client()

    def target(inputs: dict) -> dict:
        return run_conversation(agent, inputs["questions"])

    data: Any = DATASET_NAME
    if limit:
        examples = list(client.list_examples(dataset_name=DATASET_NAME))[:limit]
        data = examples

    results = evaluate(
        target,
        data=data,
        evaluators=[
            correctness_evaluator,
            hallucination_evaluator,
            context_retention_evaluator,
            efficiency_evaluator,
        ],
        experiment_prefix=f"{arm}-{model_label}",
        metadata={
            "arm": arm,
            "model": model_label,
            "judge": JUDGE_MODEL,
            "fallback": "disabled",
            "ollama_reasoning": settings.ollama_reasoning,
            "ollama_num_ctx": settings.ollama_num_ctx,
        },
        max_concurrency=concurrency,
        client=client,
    )
    print(f"\n[{arm}] experiment: {results.experiment_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("local", "cloud", "both"), default="both")
    parser.add_argument("--limit", type=int, help="Only run the first N scenarios.")
    args = parser.parse_args()

    # Traces land in LangSmith automatically; do not also pass explicit
    # callbacks or every run is recorded twice.
    os.environ.setdefault("LANGSMITH_TRACING", "true")

    arms = ("local", "cloud") if args.arm == "both" else (args.arm,)
    for arm in arms:
        # One GPU: the local arm must not run conversations in parallel.
        concurrency = 1 if arm == "local" else 4
        run_arm(arm, args.limit, concurrency)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
