"""Unit test for the SQL database adapter (uses the real read-only sqlite file)."""

from __future__ import annotations

import pytest
from langchain_community.utilities import SQLDatabase
from sqlalchemy.exc import OperationalError

from northwind_copilot.infra.database import build_database


class TestBuildDatabase:
    def test_connects_and_lists_tables(self):
        db = build_database()
        assert isinstance(db, SQLDatabase)
        tables = db.get_usable_table_names()
        # Northwind always has an Orders table; the exact set may vary.
        assert any(t.lower() == "orders" for t in tables)

    def test_reads_are_allowed(self):
        db = build_database()
        # A plain SELECT must still work through the read-only connection.
        assert "1" in db.run("SELECT 1")

    def test_writes_are_rejected(self):
        # The connection is the security boundary: any write the model might
        # emit must fail at the DB level, not merely be discouraged by a prompt.
        db = build_database()
        with pytest.raises(OperationalError, match="readonly|read-only|read only"):
            db.run("CREATE TABLE _should_not_exist (x INTEGER)")
