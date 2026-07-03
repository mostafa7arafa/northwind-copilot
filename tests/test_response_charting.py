"""Unit tests for result-SQL execution and chart inference.

``run_sql`` runs against the real ``data/northwind.sqlite`` read-only; the tests
only issue harmless SELECTs. ``infer_chart`` is a pure function.
"""

from __future__ import annotations

from northwind_copilot.response.charting import (
    _looks_temporal,
    infer_chart,
    run_sql,
)


class TestRunSql:
    def test_select_returns_columns_and_rows(self):
        out = run_sql("SELECT COUNT(*) AS n FROM Orders")
        assert out is not None
        assert out["columns"] == ["n"]
        assert out["rows"] and isinstance(out["rows"][0][0], int)
        assert out["truncated"] is False

    def test_with_cte_is_allowed(self):
        out = run_sql("WITH t AS (SELECT 1 AS x) SELECT x FROM t")
        assert out is not None and out["rows"] == [[1]]

    def test_strips_trailing_semicolon_and_fence(self):
        out = run_sql("```sql\nSELECT 1 AS x;\n```")
        assert out is not None and out["columns"] == ["x"]

    def test_empty_sql_returns_none(self):
        assert run_sql("") is None

    def test_non_select_rejected(self):
        assert run_sql("DELETE FROM Orders") is None

    def test_malformed_sql_returns_none(self):
        assert run_sql("SELECT nope FROM does_not_exist") is None


class TestLooksTemporal:
    def test_recognises_date_like_names(self):
        assert _looks_temporal("OrderDate")
        assert _looks_temporal("month")
        assert not _looks_temporal("CategoryName")


class TestInferChart:
    def test_none_or_too_few_rows(self):
        assert infer_chart(None) is None  # type: ignore[arg-type]
        assert infer_chart({"columns": ["a"], "rows": [[1]]}) is None

    def test_bar_for_categorical(self):
        table = {
            "columns": ["Category", "Revenue"],
            "rows": [["Beverages", 100], ["Seafood", 80]],
        }
        opt = infer_chart(table)
        assert opt is not None
        assert opt["series"][0]["type"] == "bar"
        assert opt["xAxis"]["data"] == ["Beverages", "Seafood"]
        assert opt["_inferred"] is True

    def test_line_for_temporal(self):
        table = {
            "columns": ["Month", "Revenue"],
            "rows": [["2017-01", 100], ["2017-02", 120]],
        }
        opt = infer_chart(table)
        assert opt is not None and opt["series"][0]["type"] == "line"

    def test_no_numeric_column(self):
        table = {
            "columns": ["A", "B"],
            "rows": [["x", "y"], ["p", "q"]],
        }
        assert infer_chart(table) is None

    def test_id_only_numeric_is_not_charted(self):
        table = {"columns": ["id", "Name"], "rows": [[1, "a"], [2, "b"]]}
        assert infer_chart(table) is None
