"""Unit tests for the benchmark graders."""

from __future__ import annotations

from northwind_copilot.eval.graders import (
    grade,
    grade_contains_all,
    grade_fields,
    grade_numeric,
    grade_rows,
    number_appears,
    text_appears,
)


class TestNumberAppears:
    def test_exact_match(self):
        assert number_appears("the answer is 14", 14)

    def test_within_relative_tolerance(self):
        # 1% tolerance absorbs rounding
        assert number_appears("AOV was 21018.70", 21018.7)
        assert number_appears("about 21100", 21018.7)

    def test_handles_thousands_separators(self):
        assert number_appears("revenue 53,265,895.23", 53265895.23)

    def test_no_match(self):
        assert not number_appears("no numbers here", 14)
        assert not number_appears("the value is 99", 14)


class TestTextAppears:
    def test_case_insensitive(self):
        assert text_appears("Top is Confections", "confections")

    def test_absent(self):
        assert not text_appears("Top is Beverages", "Seafood")


class TestGraders:
    def test_numeric(self):
        ok, _ = grade_numeric("the count is 5", 5)
        assert ok

    def test_contains_all_pass_and_fail(self):
        ok, _ = grade_contains_all(
            "Beverages, Seafood, Produce", ["Beverages", "Seafood"]
        )
        assert ok
        ok, detail = grade_contains_all("Beverages only", ["Beverages", "Seafood"])
        assert not ok and "Seafood" in detail

    def test_fields_mixed_types(self):
        ok, _ = grade_fields(
            "Top category Confections with 18320 units",
            {"category": "Confections", "quantity": 18320},
        )
        assert ok

    def test_fields_missing_value(self):
        ok, detail = grade_fields(
            "Confections only", {"category": "Confections", "quantity": 18320}
        )
        assert not ok and "quantity" in detail

    def test_rows(self):
        answer = "1. Cote de Blaye 53265895.23  2. Mishi Kobe Niku 19423037.50"
        expected = [
            {"product": "Cote de Blaye", "revenue": 53265895.23},
            {"product": "Mishi Kobe Niku", "revenue": 19423037.5},
        ]
        ok, _ = grade_rows(answer, expected)
        assert ok


class TestGradeDispatch:
    def test_dispatches_by_name(self):
        ok, _ = grade("numeric", "value 14", 14)
        assert ok

    def test_unknown_grader(self):
        ok, detail = grade("nope", "x", 1)
        assert not ok and "unknown" in detail.lower()
