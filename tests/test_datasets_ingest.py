"""Tests for dataset ingestion, including hostile-SQLite rejection."""

from __future__ import annotations

import io
import sqlite3

import pytest

from northwind_copilot.datasets import ingest
from northwind_copilot.datasets.ingest import IngestError
from northwind_copilot.datasets.schema_summary import mechanical_summary


def _csv_bytes() -> bytes:
    return b"Product Name,Unit Price,In Stock\nWidget,9.99,12\nGadget,19.5,4\n"


class TestCsv:
    def test_ingest_creates_table_and_rows(self, tmp_path):
        dest = tmp_path / "d.sqlite"
        result = ingest.ingest("csv", _csv_bytes(), dest)
        assert result.table_count == 1
        assert result.row_count == 2
        conn = sqlite3.connect(dest)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(data)")]
        conn.close()
        # Column names are sanitised to safe identifiers.
        assert "Product_Name" in cols
        assert "Unit_Price" in cols

    def test_empty_csv_rejected(self, tmp_path):
        with pytest.raises(IngestError):
            ingest.ingest("csv", b"a,b,c\n", tmp_path / "d.sqlite")


class TestXlsx:
    def test_ingest_one_table_per_sheet(self, tmp_path):
        from openpyxl import Workbook

        buf = io.BytesIO()
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "Sales"
        ws1.append(["x"])
        ws1.append([1])
        ws1.append([2])
        ws2 = wb.create_sheet("Targets")
        ws2.append(["y"])
        ws2.append([3])
        wb.save(buf)
        dest = tmp_path / "d.sqlite"
        result = ingest.ingest("xlsx", buf.getvalue(), dest)
        assert result.table_count == 2
        conn = sqlite3.connect(dest)
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert {"Sales", "Targets"} <= names


class TestSqlite:
    def _make_db(self, path, with_view=False, with_trigger=False):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sales (id INTEGER, amount REAL)")
        conn.executemany("INSERT INTO sales VALUES (?, ?)", [(1, 10.0), (2, 20.0)])
        if with_view:
            conn.execute("CREATE VIEW v AS SELECT * FROM sales")
        if with_trigger:
            conn.execute("CREATE TRIGGER t AFTER INSERT ON sales BEGIN SELECT 1; END")
        conn.commit()
        conn.close()

    def test_ingest_copies_table_data(self, tmp_path):
        src = tmp_path / "src.sqlite"
        self._make_db(src)
        dest = tmp_path / "d.sqlite"
        result = ingest.ingest("sqlite", src.read_bytes(), dest)
        assert result.table_count == 1
        assert result.row_count == 2

    def test_views_and_triggers_are_shed(self, tmp_path):
        src = tmp_path / "src.sqlite"
        self._make_db(src, with_view=True, with_trigger=True)
        dest = tmp_path / "d.sqlite"
        ingest.ingest("sqlite", src.read_bytes(), dest)
        conn = sqlite3.connect(dest)
        kinds = {
            r[0]
            for r in conn.execute(
                "SELECT type FROM sqlite_master WHERE type IN " "('view','trigger')"
            )
        }
        conn.close()
        # The fresh file carries only table data — no views or triggers.
        assert kinds == set()

    def test_non_sqlite_bytes_rejected(self, tmp_path):
        with pytest.raises(IngestError, match="not a valid SQLite"):
            ingest.ingest("sqlite", b"this is not a database", tmp_path / "d.sqlite")


class TestSchemaSummary:
    def test_summary_lists_tables_and_columns(self, tmp_path):
        dest = tmp_path / "d.sqlite"
        ingest.ingest("csv", _csv_bytes(), dest)
        summary = mechanical_summary(dest)
        assert "Table data" in summary
        assert "Product_Name" in summary
        assert "Widget" in summary  # a sample value


def test_unsupported_source_type(tmp_path):
    with pytest.raises(IngestError):
        ingest.ingest("json", b"{}", tmp_path / "d.sqlite")
