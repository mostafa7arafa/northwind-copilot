"""Convert an uploaded file into a per-tenant read-only SQLite dataset.

Security posture: the uploaded bytes are untrusted. Tabular files (CSV/XLSX) are
parsed with pandas and written to a *fresh* SQLite file, so nothing executable
survives. Uploaded SQLite files are the dangerous case — they can carry triggers,
views, virtual tables, or hostile content in free pages — so we never serve the
uploaded file directly: we open it read-only, validate it, then copy only real
table *data* into a fresh file (shedding triggers/views/virtual tables entirely).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# The 16-byte magic every SQLite 3 database file begins with.
_SQLITE_MAGIC = b"SQLite format 3\x00"
# Guardrails on uploaded SQLite structure (tier upload-size caps bound volume).
_MAX_TABLES = 100


class IngestError(ValueError):
    """Raised when an uploaded file cannot be safely ingested."""


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a successful ingestion."""

    table_count: int
    row_count: int


def _sane_identifier(name: str, fallback: str) -> str:
    """Coerce an arbitrary string into a safe SQL identifier."""
    cleaned = re.sub(r"\W+", "_", str(name).strip()).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned[:63]


def _sane_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with column names coerced to unique safe identifiers."""
    seen: dict[str, int] = {}
    new_cols = []
    for i, col in enumerate(df.columns):
        base = _sane_identifier(col, f"col_{i}")
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        new_cols.append(base)
    df = df.copy()
    df.columns = new_cols
    return df


def _write_frame(df: pd.DataFrame, table: str, dest: Path) -> int:
    """Write one DataFrame to ``dest`` as ``table``; return its row count."""
    df = _sane_columns(df)
    conn = sqlite3.connect(dest)
    try:
        df.to_sql(table, conn, index=False, if_exists="replace")
    finally:
        conn.close()
    return len(df)


def ingest_csv(data: bytes, dest: Path, *, table: str = "data") -> IngestResult:
    """Ingest CSV bytes into a single-table SQLite file."""
    import io

    try:
        df = pd.read_csv(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - report a clean ingest failure
        raise IngestError(f"Could not parse CSV: {exc}") from exc
    if df.empty:
        raise IngestError("The CSV file has no rows.")
    rows = _write_frame(df, _sane_identifier(table, "data"), dest)
    return IngestResult(table_count=1, row_count=rows)


def ingest_xlsx(data: bytes, dest: Path) -> IngestResult:
    """Ingest an Excel workbook, one table per sheet."""
    import io

    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Could not parse Excel file: {exc}") from exc
    total_rows = 0
    tables = 0
    for sheet_name, df in sheets.items():
        if df.empty:
            continue
        total_rows += _write_frame(df, _sane_identifier(sheet_name, "sheet"), dest)
        tables += 1
    if tables == 0:
        raise IngestError("The Excel file has no non-empty sheets.")
    return IngestResult(table_count=tables, row_count=total_rows)


def ingest_sqlite(data: bytes, dest: Path) -> IngestResult:
    """Ingest an uploaded SQLite file by copying only real table data.

    Validates the file, then re-materialises each ordinary table into a fresh
    database. Triggers, views, and virtual tables are intentionally NOT copied.
    """
    if not data.startswith(_SQLITE_MAGIC):
        raise IngestError("File is not a valid SQLite database.")

    tmp = dest.with_suffix(".upload.tmp")
    tmp.write_bytes(data)
    try:
        ro = sqlite3.connect(f"file:{tmp}?mode=ro&immutable=1", uri=True)
        try:
            if ro.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise IngestError("The SQLite database failed an integrity check.")
            master = ro.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            # Skip internal tables and anything declared as a virtual table.
            real = [
                name
                for name, sql in master
                if not name.startswith("sqlite_")
                and "virtual table" not in (sql or "").lower()
            ]
            if not real:
                raise IngestError("The SQLite database has no readable tables.")
            if len(real) > _MAX_TABLES:
                raise IngestError(f"Too many tables (max {_MAX_TABLES}).")

            total_rows = 0
            for name in real:
                df = pd.read_sql(f'SELECT * FROM "{name}"', ro)
                total_rows += _write_frame(df, _sane_identifier(name, "table"), dest)
        finally:
            ro.close()
    finally:
        tmp.unlink(missing_ok=True)

    return IngestResult(table_count=len(real), row_count=total_rows)


def ingest(source_type: str, data: bytes, dest: Path) -> IngestResult:
    """Dispatch to the ingester for ``source_type`` (csv | xlsx | sqlite)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    if source_type == "csv":
        return ingest_csv(data, dest)
    if source_type == "xlsx":
        return ingest_xlsx(data, dest)
    if source_type == "sqlite":
        return ingest_sqlite(data, dest)
    raise IngestError(f"Unsupported source type: {source_type!r}")
