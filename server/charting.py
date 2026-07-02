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
from pathlib import Path
from typing import Any

from northwind_copilot.config import settings

_MAX_ROWS = 500
_NUMERIC = (int, float)


def _db_path() -> Path:
    """Resolve the on-disk SQLite path from the configured URI."""
    uri = settings.database_uri
    path = uri.replace("sqlite:///", "").replace("sqlite://", "")
    return Path(path)


def run_sql(sql: str) -> dict[str, Any] | None:
    """Run a read-only SELECT and return structured columns and rows.

    Args:
        sql: The SQL statement captured from the agent's query tool call.

    Returns:
        ``{"columns": [...], "rows": [[...]], "truncated": bool}`` on success,
        or ``None`` if the statement is empty, non-SELECT, or errors.
    """
    if not sql:
        return None
    cleaned = sql.strip().rstrip(";").strip()
    # Strip a stray markdown fence if one slipped through.
    cleaned = re.sub(r"^```(?:sql)?|```$", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned.lower().startswith(("select", "with")):
        return None

    try:
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
        try:
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
