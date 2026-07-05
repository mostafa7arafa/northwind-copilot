"""Describe an ingested SQLite dataset for prompting and onboarding.

The mechanical summary (tables, columns, types, a few sample values) is derived
directly from the file and is always available. An optional LLM enrichment turns
that into a short natural-language description of what the dataset appears to
contain; it is injected as a callable so this module — and its tests — never
depend on a live model.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

_SAMPLES_PER_COLUMN = 3
_MAX_TABLES_DESCRIBED = 40


def mechanical_summary(sqlite_path: str | Path) -> str:
    """Introspect a SQLite file into a compact schema description.

    Args:
        sqlite_path: Path to the dataset's SQLite file.

    Returns:
        A plain-text block listing each table, its columns and types, its row
        count, and a few sample values per column.
    """
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        blocks: list[str] = []
        for table in tables[:_MAX_TABLES_DESCRIBED]:
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            try:
                row_count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[
                    0
                ]
            except sqlite3.Error:
                row_count = 0
            lines = [f"Table {table} ({row_count} rows):"]
            for col in cols:
                col_name, col_type = col[1], col[2] or "TEXT"
                samples = conn.execute(
                    f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                    f'WHERE "{col_name}" IS NOT NULL LIMIT {_SAMPLES_PER_COLUMN}'
                ).fetchall()
                sample_str = ", ".join(str(s[0]) for s in samples)
                suffix = f" e.g. {sample_str}" if sample_str else ""
                lines.append(f"  - {col_name} ({col_type}){suffix}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
    finally:
        conn.close()


def generate_summary(
    sqlite_path: str | Path,
    describe: Callable[[str], str] | None = None,
) -> str:
    """Build the stored schema summary for a dataset.

    Args:
        sqlite_path: Path to the dataset's SQLite file.
        describe: Optional callable that turns the mechanical summary into a
            short natural-language overview (e.g. one cheap LLM call). When
            ``None``, only the mechanical summary is returned.

    Returns:
        The schema summary text to store on the dataset row.
    """
    mechanical = mechanical_summary(sqlite_path)
    if describe is None:
        return mechanical
    try:
        overview = describe(mechanical).strip()
    except Exception:  # noqa: BLE001 - enrichment is best-effort, never fatal
        overview = ""
    if not overview:
        return mechanical
    return f"{overview}\n\n{mechanical}"
