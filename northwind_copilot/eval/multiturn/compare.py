"""Print a side-by-side comparison of two multi-turn experiments.

Usage:
    python -m northwind_copilot.eval.multiturn.compare <local-exp> <cloud-exp>
"""

from __future__ import annotations

import truststore

truststore.inject_into_ssl()

import argparse  # noqa: E402
from statistics import mean  # noqa: E402

from langsmith import Client  # noqa: E402

from northwind_copilot.core.config import settings  # noqa: E402  (loads .env)

assert settings  # keep the import; it is what loads .env

JUDGED = ("correctness", "no_hallucination", "context_retention")
PER_TURN = (
    "correctness_t1",
    "correctness_t2",
    "correctness_t3",
    "no_hallucination_t1",
    "no_hallucination_t2",
    "no_hallucination_t3",
)
EFFICIENCY = (
    "latency_s_total",
    "latency_s_per_turn",
    "tokens_in",
    "tokens_out",
    "model_calls",
    "turn_errors",
)


def load(client: Client, project: str) -> dict[str, dict[str, float]]:
    """Return ``{scenario_id: {feedback_key: score}}`` for one experiment."""
    out: dict[str, dict[str, float]] = {}
    for run in client.list_runs(project_name=project, is_root=True):
        scores = {
            f.key: f.score
            for f in client.list_feedback(run_ids=[run.id])
            if f.score is not None
        }
        out[run.inputs["scenario_id"]] = scores
    return out


def avg(data: dict[str, dict[str, float]], key: str) -> float | None:
    """Mean of one feedback key across scenarios that have it."""
    values = [s[key] for s in data.values() if key in s]
    return mean(values) if values else None


def _fmt(value: float | None, pct: bool) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.2f}"


def _row(label: str, a: float | None, b: float | None, pct: bool) -> str:
    return f"  {label:22s} {_fmt(a, pct):>10s} {_fmt(b, pct):>14s}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("local_experiment")
    parser.add_argument("cloud_experiment")
    args = parser.parse_args()

    client = Client()
    local = load(client, args.local_experiment)
    cloud = load(client, args.cloud_experiment)

    shared = sorted(set(local) & set(cloud))
    print(f"Scenarios compared: {len(shared)} (local {len(local)}, cloud {len(cloud)})")
    print(f"\n{'':24s}{'gemma4-12b':>10s}{'gpt-4.1-mini':>15s}")
    print("  " + "-" * 46)
    print("  JUDGED (higher is better)")
    for key in JUDGED:
        print(_row(key, avg(local, key), avg(cloud, key), pct=True))
    print("\n  PER TURN")
    for key in PER_TURN:
        print(_row(key, avg(local, key), avg(cloud, key), pct=True))
    print("\n  COST / SPEED (lower is better)")
    for key in EFFICIENCY:
        print(_row(key, avg(local, key), avg(cloud, key), pct=False))

    print("\n  Scenarios where the arms disagree on correctness:")
    disagreements = 0
    for sid in shared:
        a, b = local[sid].get("correctness"), cloud[sid].get("correctness")
        if a is None or b is None or abs(a - b) < 1e-9:
            continue
        disagreements += 1
        winner = "cloud" if b > a else "LOCAL"
        print(f"    {sid:34s} local={a:.2f}  cloud={b:.2f}   -> {winner}")
    if not disagreements:
        print("    (none)")

    print("\n  Hallucination probe (missing_year_1997):")
    for name, data in (("local", local), ("cloud", cloud)):
        s = data.get("missing_year_1997", {})
        print(
            f"    {name:6s} correctness_t1={s.get('correctness_t1')}  "
            f"no_hallucination_t1={s.get('no_hallucination_t1')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
