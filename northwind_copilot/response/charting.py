"""Execute result SQL cleanly and derive a chart when the model didn't draw one.

Two jobs:

* :func:`run_sql` re-runs the agent's final ``SELECT`` directly against the
  SQLite file so the frontend gets structured columns/rows rather than the
  string blob the SQL tool returns.
* :func:`infer_chart` builds a reasonable Apache ECharts ``option`` from a result
  table. Cloud models draw their own chart; local models rely on this.
"""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from sqlalchemy.engine.url import make_url

from northwind_copilot.core.config import settings

_MAX_ROWS = 500
_NUMERIC = (int, float)


def _db_path() -> str | None:
    """Resolve the on-disk SQLite path from the configured URI.

    Returns:
        The database file path, or ``None`` when the configured backend is not
        a file-backed SQLite database (in which case direct re-execution here
        does not apply).
    """
    url = make_url(settings.database_uri)
    if url.get_backend_name() != "sqlite":
        return None
    return url.database or None


def _deadline_guard(seconds: float):
    """Build a SQLite progress handler that aborts a query past a time budget.

    SQLite calls the handler periodically during execution; returning non-zero
    raises ``sqlite3.OperationalError`` and unwinds the query. This bounds a
    pathological (e.g. accidental cartesian) query so it can't pin a core.

    Args:
        seconds: The wall-clock budget for the query.

    Returns:
        A zero-arg callable suitable for ``connection.set_progress_handler``.
    """
    deadline = time.monotonic() + seconds

    def handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    return handler


def run_sql(sql: str) -> dict[str, Any] | None:
    """Run a read-only SELECT and return structured columns and rows.

    Args:
        sql: The SQL statement captured from the agent's query tool call.

    Returns:
        ``{"columns": [...], "rows": [[...]], "truncated": bool}`` on success,
        or ``None`` if the statement is empty, non-SELECT, times out, or errors.
    """
    if not sql:
        return None
    path = _db_path()
    if path is None:
        return None
    cleaned = sql.strip().rstrip(";").strip()
    # Strip a stray markdown fence if one slipped through.
    cleaned = re.sub(r"^```(?:sql)?|```$", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned.lower().startswith(("select", "with")):
        return None

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            # Abort the query if it runs past the configured budget. The count
            # is how many VM instructions between handler calls — small enough
            # to react promptly, large enough not to dominate runtime.
            conn.set_progress_handler(
                _deadline_guard(settings.query_timeout_seconds), 10_000
            )
            cursor = conn.execute(cleaned)
            columns = [c[0] for c in cursor.description or []]
            raw = cursor.fetchmany(_MAX_ROWS + 1)
        finally:
            conn.close()
    except sqlite3.Error:
        return None

    truncated = len(raw) > _MAX_ROWS
    rows = [list(r) for r in raw[:_MAX_ROWS]]
    return {"columns": columns, "rows": rows, "truncated": truncated}


def _looks_temporal(name: str) -> bool:
    """Heuristic: does a column name read like a date/period axis?"""
    n = name.lower()
    return any(k in n for k in ("date", "month", "year", "period", "day", "week"))


def infer_chart(table: dict[str, Any]) -> dict[str, Any] | None:
    """Derive an ECharts option from a result table.

    Picks the first non-numeric column as the category axis and every numeric
    column as a series. Uses a line for temporal categories, otherwise bars; a
    single-row single-value result yields nothing (not worth charting).

    Args:
        table: The structured table from :func:`run_sql`.

    Returns:
        An ECharts ``option`` dict, or ``None`` when the data isn't chartable.
    """
    if not table:
        return None
    columns: list[str] = table["columns"]
    rows: list[list] = table["rows"]
    if not columns or not rows or len(rows) < 2:
        return None

    numeric_idx = [
        i
        for i in range(len(columns))
        if all(isinstance(r[i], _NUMERIC) for r in rows if r[i] is not None)
        and any(r[i] is not None for r in rows)
    ]
    if not numeric_idx:
        return None

    label_idx = next((i for i in range(len(columns)) if i not in numeric_idx), None)
    if label_idx is None:
        return None
    # Don't chart obvious id columns as the sole series.
    numeric_idx = [i for i in numeric_idx if columns[i].lower() not in ("id",)]
    if not numeric_idx:
        return None

    categories = [str(r[label_idx]) for r in rows]
    chart_type = "line" if _looks_temporal(columns[label_idx]) else "bar"
    series = [
        {
            "name": columns[i],
            "type": chart_type,
            "smooth": chart_type == "line",
            "data": [r[i] for r in rows],
        }
        for i in numeric_idx
    ]

    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": len(series) > 1},
        "grid": {
            "left": 48,
            "right": 24,
            "top": 32,
            "bottom": 40,
            "containLabel": True,
        },
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": series,
        "_inferred": True,
    }
