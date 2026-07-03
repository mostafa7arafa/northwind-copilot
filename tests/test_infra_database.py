"""Unit test for the SQL database adapter (uses the real read-only sqlite file)."""

from __future__ import annotations

from langchain_community.utilities import SQLDatabase

from northwind_copilot.infra.database import build_database


class TestBuildDatabase:
    def test_connects_and_lists_tables(self):
        db = build_database()
        assert isinstance(db, SQLDatabase)
        tables = db.get_usable_table_names()
        # Northwind always has an Orders table; the exact set may vary.
        assert any(t.lower() == "orders" for t in tables)
