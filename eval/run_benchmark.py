"""Benchmark runner for the Northwind copilot agent.

Runs each question in benchmark_dataset.jsonl through the agent, grades the
final answer against the precomputed ground truth, and records which model
actually produced the answer (gemma primary vs gpt fallback) plus latency.

Usage:
    python -m eval.run_benchmark                 # run all
    python -m eval.run_benchmark --id sql_employee_count_usa
    python -m eval.run_benchmark --limit 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

# Harmless noise from langchain serializing ChatOllama state in the checkpointer.
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic.main")
from datetime import datetime, timezone
from pathlib import Path

from eval.graders import grade

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "benchmark_dataset.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def extract_answer(messages) -> str:
    """Last AI message with textual content."""
    for msg in reversed(messages):
        content = getattr(msg, "content", "")
        if getattr(msg, "type", "") == "ai" and content:
            if isinstance(content, list):  # some providers return content blocks
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            if content.strip():
                return content
    return ""


def models_used(messages) -> list[str]:
    """Distinct model names seen across AI messages, in order of appearance."""
    seen: list[str] = []
    for msg in messages:
        meta = getattr(msg, "response_metadata", {}) or {}
        name = meta.get("model_name") or meta.get("model")
        if name and name not in seen:
            seen.append(name)
    return seen


def run_one(graph, record: dict) -> dict:
    question = record["question"]
    start = time.perf_counter()
    error = None
    answer = ""
    models: list[str] = []
    try:
        result = graph.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": record["id"]},
                    "recursion_limit": 50},
        )
        messages = result["messages"]
        answer = extract_answer(messages)
        models = models_used(messages)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the suite
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start

    if error:
        passed, detail = False, error
    else:
        passed, detail = grade(record["grader"], answer, record["expected"])

    return {
        "id": record["id"],
        "passed": passed,
        "detail": detail,
        "models": models,
        "latency_s": round(latency, 2),
        "answer": answer,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Northwind agent benchmark.")
    parser.add_argument("--id", action="append", help="Only run these id(s).")
    parser.add_argument("--limit", type=int, help="Run at most N questions.")
    parser.add_argument("--no-save", action="store_true", help="Skip writing results JSON.")
    args = parser.parse_args()

    records = load_dataset(DATASET)
    if args.id:
        wanted = set(args.id)
        records = [r for r in records if r["id"] in wanted]
    if args.limit:
        records = records[: args.limit]
    if not records:
        print("No matching benchmark records.", file=sys.stderr)
        return 1

    print(f"Loading agent... ({len(records)} question(s) to run)")
    from agent.agent import graph  # imported lazily so --help is instant

    results = []
    for i, record in enumerate(records, 1):
        print(f"[{i}/{len(records)}] {record['id']} ...", end=" ", flush=True)
        res = run_one(graph, record)
        results.append(res)
        mark = "PASS" if res["passed"] else "FAIL"
        model = res["models"][-1] if res["models"] else "?"
        print(f"{mark}  ({res['latency_s']}s, {model})")
        if not res["passed"]:
            print(f"      {res['detail']}")

    passed = sum(r["passed"] for r in results)
    total = len(results)
    avg_latency = round(sum(r["latency_s"] for r in results) / total, 2)
    fallback_used = sum(
        1 for r in results if any("gpt" in m.lower() for m in r["models"])
    )

    print("\n" + "=" * 56)
    print(f"  Accuracy : {passed}/{total} ({100 * passed / total:.0f}%)")
    print(f"  Avg time : {avg_latency}s")
    print(f"  Fallback : {fallback_used}/{total} used gpt fallback")
    print("=" * 56)

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary = {
            "timestamp": stamp,
            "accuracy": passed / total,
            "passed": passed,
            "total": total,
            "avg_latency_s": avg_latency,
            "fallback_used": fallback_used,
            "results": results,
        }
        for name in (f"{stamp}.json", "latest.json"):
            (RESULTS_DIR / name).write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        print(f"Saved -> eval/results/latest.json")

    return 0 if passed == total else 2


if __name__ == "__main__":
    raise SystemExit(main())
