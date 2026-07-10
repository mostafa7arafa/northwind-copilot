"""Compute ground truth for every scenario turn and publish the dataset.

Ground truth is produced by running each turn's ``reference_sql`` against the
Northwind database, so no expected value in this dataset was written by hand.
The result is written to ``multiturn_dataset.jsonl`` at the repo root (the local
copy, committed) and optionally pushed to LangSmith as a versioned dataset.

Usage:
    python -m northwind_copilot.eval.multiturn.build_dataset            # local only
    python -m northwind_copilot.eval.multiturn.build_dataset --push     # + LangSmith
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from northwind_copilot.core.config import settings
from northwind_copilot.eval.multiturn.scenarios import SCENARIOS, Scenario, Turn

ROOT = Path(__file__).resolve().parents[3]
LOCAL_COPY = ROOT / "multiturn_dataset.jsonl"

DATASET_NAME = "northwind-multiturn-analyst"
DATASET_DESCRIPTION = (
    "22 scripted 3-turn analyst conversations over the Northwind database. "
    "Ground truth for each turn is computed by executing that turn's reference "
    "SQL, never written by hand. Used to compare a local Ollama model against a "
    "cloud model on correctness, hallucination, and context retention."
)


def _sqlite_path() -> Path:
    """Resolve the Northwind SQLite file from the configured SQLAlchemy URI."""
    uri = settings.database_uri
    prefix = "sqlite:///"
    if not uri.startswith(prefix):
        raise ValueError(f"Expected a sqlite:/// URI, got {uri!r}")
    path = Path(uri[len(prefix) :])
    return path if path.is_absolute() else ROOT / path


def render_rows(rows: list[dict[str, Any]]) -> str:
    """Render result rows as compact, judge-readable ground truth.

    Args:
        rows: Query results as column->value mappings.

    Returns:
        One ``col=value`` line per row, or an explicit no-rows marker.
    """
    if not rows:
        return "(no rows)"
    return "\n".join(
        "; ".join(f"{col}={val}" for col, val in row.items()) for row in rows
    )


def execute(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    """Run a reference query and return its rows as dicts."""
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_turn(conn: sqlite3.Connection, turn: Turn, position: int) -> dict[str, Any]:
    """Compute one turn's ground truth from its reference SQL.

    Args:
        conn: Open connection to the Northwind database.
        turn: The scenario turn to resolve.
        position: 1-based turn index within its scenario.

    Returns:
        A serialisable turn record carrying question, reference, and probes.

    Raises:
        ValueError: If a turn expected to return rows returns none (a broken
            reference query would silently poison the whole experiment).
    """
    rows = execute(conn, turn.reference_sql)
    expects_empty = "empty_result" in turn.probes

    if rows and expects_empty:
        raise ValueError(
            f"turn {position} is an empty_result probe but its reference SQL "
            f"returned {len(rows)} row(s)"
        )
    if not rows and not expects_empty:
        raise ValueError(
            f"turn {position} returned no rows; its reference SQL is wrong"
        )

    reference = turn.reference_override or render_rows(rows)
    return {
        "position": position,
        "question": turn.question,
        "reference": reference,
        "reference_rows": rows,
        "reference_sql": " ".join(turn.reference_sql.split()),
        "probes": list(turn.probes),
    }


def build_scenario(conn: sqlite3.Connection, scenario: Scenario) -> dict[str, Any]:
    """Compute ground truth for every turn of one scenario."""
    turns = [build_turn(conn, t, i) for i, t in enumerate(scenario.turns, 1)]
    return {
        "id": scenario.id,
        "title": scenario.title,
        "tags": list(scenario.tags),
        "turns": turns,
    }


def build_all() -> list[dict[str, Any]]:
    """Build every scenario, failing loudly on a bad reference query."""
    db = _sqlite_path()
    if not db.exists():
        raise FileNotFoundError(f"Northwind database not found at {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = []
        for scenario in SCENARIOS:
            try:
                out.append(build_scenario(conn, scenario))
            except ValueError as exc:
                raise ValueError(f"scenario {scenario.id!r}: {exc}") from exc
        return out
    finally:
        conn.close()


def write_local(records: list[dict[str, Any]]) -> None:
    """Write the committed local copy as JSONL."""
    with LOCAL_COPY.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _langsmith_client():
    """Build a LangSmith client, relaxing TLS when INSECURE_TLS is set.

    The corporate network intercepts TLS, so the default verifying session
    fails to reach api.smith.langchain.com. Mirrors the approach already used
    by ``response.streaming._tracing_callbacks``.
    """
    import requests
    from langsmith import Client

    session = requests.Session()
    if settings.insecure_tls:
        session.verify = False
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return Client(session=session)


def _example_payload(record: dict[str, Any]) -> tuple[dict, dict, dict]:
    """Split one record into LangSmith ``(inputs, outputs, metadata)``."""
    inputs = {
        "scenario_id": record["id"],
        "title": record["title"],
        "questions": [t["question"] for t in record["turns"]],
    }
    outputs = {
        "turns": [
            {
                "position": t["position"],
                "reference": t["reference"],
                "reference_sql": t["reference_sql"],
            }
            for t in record["turns"]
        ]
    }
    metadata = {
        "tags": record["tags"],
        "probes": sorted({p for t in record["turns"] for p in t["probes"]}),
        "n_turns": len(record["turns"]),
    }
    return inputs, outputs, metadata


def push(records: list[dict[str, Any]]) -> str:
    """Create the dataset, or update it in place as a new version.

    Deliberately does NOT delete and recreate: deleting a LangSmith dataset takes
    its experiments with it, and the whole point of the dataset is to accumulate
    comparable experiments over time. Updating an example creates a new dataset
    version and leaves prior runs intact.

    Returns:
        The dataset URL.
    """
    client = _langsmith_client()

    if not client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME, description=DATASET_DESCRIPTION
        )
        payloads = [_example_payload(r) for r in records]
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[p[0] for p in payloads],
            outputs=[p[1] for p in payloads],
            metadata=[p[2] for p in payloads],
        )
        return f"https://smith.langchain.com/datasets/{dataset.id}"

    dataset = client.read_dataset(dataset_name=DATASET_NAME)
    existing = {
        ex.inputs["scenario_id"]: ex
        for ex in client.list_examples(dataset_id=dataset.id)
    }

    to_create, update_ids, update_payloads = [], [], []
    for record in records:
        payload = _example_payload(record)
        found = existing.pop(record["id"], None)
        if found is None:
            to_create.append(payload)
        else:
            update_ids.append(found.id)
            update_payloads.append(payload)

    if update_ids:
        client.update_examples(
            example_ids=update_ids,
            inputs=[p[0] for p in update_payloads],
            outputs=[p[1] for p in update_payloads],
            metadata=[p[2] for p in update_payloads],
        )
    if to_create:
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[p[0] for p in to_create],
            outputs=[p[1] for p in to_create],
            metadata=[p[2] for p in to_create],
        )
    # Scenarios that no longer exist (e.g. renamed) must not linger.
    for stale in existing.values():
        client.delete_example(example_id=stale.id)

    print(
        f"  updated={len(update_ids)} created={len(to_create)} "
        f"removed={len(existing)}"
    )
    return f"https://smith.langchain.com/datasets/{dataset.id}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--push", action="store_true", help="Also publish the dataset to LangSmith."
    )
    args = parser.parse_args()

    records = build_all()
    write_local(records)

    n_turns = sum(len(r["turns"]) for r in records)
    print(f"Built {len(records)} scenarios / {n_turns} turns")
    print(f"Local copy -> {LOCAL_COPY.relative_to(ROOT)}")

    if args.push:
        url = push(records)
        print(f"LangSmith  -> {url}")
    else:
        print("(not pushed; pass --push to publish to LangSmith)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
