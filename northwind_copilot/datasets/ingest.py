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


# ---------------------------------------------------------------------------
# Multi-file datasets: append a file's tables to an existing dataset
# ---------------------------------------------------------------------------


def _existing_tables(dest: Path) -> set[str]:
    """Return the table names already present in a dataset file."""
    conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    try:
        return {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()


def _unique_table(base: str, taken: set[str]) -> str:
    """Return ``base`` or the first ``base_N`` not already taken."""
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def dataset_stats(dest: Path) -> tuple[int, int]:
    """Recount a dataset file's tables and total rows (source of truth).

    Used after an append so the stored counts always reflect the file, even
    if a multi-sheet append failed partway through.
    """
    conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        rows = 0
        for table in tables:
            try:
                rows += conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.Error:
                continue
        return len(tables), rows
    finally:
        conn.close()


def append(
    source_type: str, data: bytes, dest: Path, *, name_hint: str = "data"
) -> IngestResult:
    """Add one more file's tables to an existing dataset SQLite.

    This is what makes datasets *relational across files*: each appended
    upload becomes another table in the same per-tenant database, so the
    agent can join sales.csv against targets.xlsx. Table names come from the
    filename (CSV) or sheet names (XLSX) and are de-conflicted with an ``_N``
    suffix rather than replaced — appends never clobber existing data.

    Args:
        source_type: ``csv`` | ``xlsx`` | ``sqlite``.
        data: The uploaded file's bytes (untrusted; same posture as `ingest`).
        dest: The dataset's existing SQLite file.
        name_hint: Base table name for single-table sources (the filename stem).

    Returns:
        Counts for the tables/rows *added* by this call.

    Raises:
        IngestError: When the file can't be parsed, the dataset file is
            missing, or the table cap would be exceeded.
    """
    if not dest.exists():
        raise IngestError("Dataset file not found.")
    taken = _existing_tables(dest)

    def _check_cap(adding: int) -> None:
        if len(taken) + adding > _MAX_TABLES:
            raise IngestError(f"Too many tables (max {_MAX_TABLES}).")

    if source_type == "csv":
        import io

        try:
            df = pd.read_csv(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Could not parse CSV: {exc}") from exc
        if df.empty:
            raise IngestError("The CSV file has no rows.")
        _check_cap(1)
        table = _unique_table(_sane_identifier(name_hint, "data"), taken)
        rows = _write_frame(df, table, dest)
        return IngestResult(table_count=1, row_count=rows)

    if source_type == "xlsx":
        import io

        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        except Exception as exc:  # noqa: BLE001
            raise IngestError(f"Could not parse Excel file: {exc}") from exc
        non_empty = {n: df for n, df in sheets.items() if not df.empty}
        if not non_empty:
            raise IngestError("The Excel file has no non-empty sheets.")
        _check_cap(len(non_empty))
        total_rows = 0
        added = 0
        for sheet_name, df in non_empty.items():
            table = _unique_table(_sane_identifier(sheet_name, "sheet"), taken)
            taken.add(table)
            total_rows += _write_frame(df, table, dest)
            added += 1
        return IngestResult(table_count=added, row_count=total_rows)

    if source_type == "sqlite":
        if not data.startswith(_SQLITE_MAGIC):
            raise IngestError("File is not a valid SQLite database.")
        tmp = dest.with_suffix(".append.tmp")
        tmp.write_bytes(data)
        try:
            ro = sqlite3.connect(f"file:{tmp}?mode=ro&immutable=1", uri=True)
            try:
                if ro.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise IngestError("The SQLite database failed an integrity check.")
                master = ro.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                real = [
                    name
                    for name, sql in master
                    if not name.startswith("sqlite_")
                    and "virtual table" not in (sql or "").lower()
                ]
                if not real:
                    raise IngestError("The SQLite database has no readable tables.")
                _check_cap(len(real))
                total_rows = 0
                for name in real:
                    df = pd.read_sql(f'SELECT * FROM "{name}"', ro)
                    table = _unique_table(_sane_identifier(name, "table"), taken)
                    taken.add(table)
                    total_rows += _write_frame(df, table, dest)
            finally:
                ro.close()
        finally:
            tmp.unlink(missing_ok=True)
        return IngestResult(table_count=len(real), row_count=total_rows)

    raise IngestError(f"Unsupported source type: {source_type!r}")
