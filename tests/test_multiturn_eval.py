"""Offline tests for the multi-turn eval dataset and its scorers.

No LLM and no network: these guard the *measuring instrument*. A silently wrong
reference query does not fail an experiment — it produces a confident, wrong
comparison, which is worse.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from northwind_copilot.eval.multiturn.build_dataset import build_all, render_rows
from northwind_copilot.eval.multiturn.run_experiment import (
    _as_score,
    _format_call,
    _strip_charts,
)
from northwind_copilot.eval.multiturn.scenarios import (
    SCENARIOS,
    scenario_count,
    turn_count,
)

DB = Path("data/northwind.sqlite")

# The ORDER BY key here is HireDate, which is unique; only the *displayed*
# column (Title) repeats, so the generic tie heuristic false-positives.
TIE_CHECK_WHITELIST = {("longest_serving_employee", 2)}


@pytest.fixture(scope="module")
def conn():
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    yield connection
    connection.close()


class TestScenarioShape:
    def test_counts(self):
        assert scenario_count() == 23
        assert turn_count() == 69

    def test_scenario_ids_are_unique(self):
        ids = [s.id for s in SCENARIOS]
        assert len(ids) == len(set(ids))

    def test_every_scenario_probes_reference_resolution(self):
        # A multi-turn suite whose later turns don't refer back is just a
        # single-turn suite run three times.
        for scenario in SCENARIOS:
            probes = {p for t in scenario.turns for p in t.probes}
            assert "reference_resolution" in probes, scenario.id

    def test_exactly_one_empty_result_probe(self):
        empties = [
            (s.id, i)
            for s in SCENARIOS
            for i, t in enumerate(s.turns, 1)
            if "empty_result" in t.probes
        ]
        assert empties == [("missing_year_1997", 1)]


class TestReferenceGroundTruth:
    def test_every_reference_query_executes(self, conn):
        for scenario in SCENARIOS:
            for i, turn in enumerate(scenario.turns, 1):
                conn.execute(turn.reference_sql)  # raises on bad SQL

    def test_non_empty_probes_return_rows(self, conn):
        for scenario in SCENARIOS:
            for i, turn in enumerate(scenario.turns, 1):
                rows = conn.execute(turn.reference_sql).fetchall()
                if "empty_result" in turn.probes:
                    assert rows == [], f"{scenario.id} T{i} should return no rows"
                else:
                    assert rows, f"{scenario.id} T{i} returned no rows"

    def test_no_ambiguous_top_1_reference(self, conn):
        """A tied ORDER BY makes two answers correct but marks one wrong.

        This regression guards a real bug: `supplier_breadth` once ranked
        suppliers by product count, where Pavlova and Plutzer both have 5, and
        `highest_freight_2016` had two orders tied at freight 534.0. Both
        penalised a correct model.
        """
        ambiguous = []
        for scenario in SCENARIOS:
            for i, turn in enumerate(scenario.turns, 1):
                if (scenario.id, i) in TIE_CHECK_WHITELIST:
                    continue
                sql = " ".join(turn.reference_sql.split()).rstrip()
                if not sql.upper().endswith("LIMIT 1"):
                    continue
                rows = conn.execute(sql[: -len("LIMIT 1")] + " LIMIT 2").fetchall()
                if len(rows) > 1 and rows[0][-1] == rows[1][-1]:
                    ambiguous.append(f"{scenario.id} T{i}: {rows[0]} == {rows[1]}")
        assert not ambiguous, "tied reference answers: " + "; ".join(ambiguous)

    def test_build_all_produces_full_ground_truth(self):
        records = build_all()
        assert len(records) == 23
        assert sum(len(r["turns"]) for r in records) == 69
        for record in records:
            for turn in record["turns"]:
                assert turn["reference"].strip()

    def test_empty_result_turn_carries_refusal_text(self):
        record = next(r for r in build_all() if r["id"] == "missing_year_1997")
        reference = record["turns"][0]["reference"]
        assert "no orders in 1997" in reference.lower()
        assert record["turns"][0]["reference_rows"] == []


class TestRenderRows:
    def test_renders_no_rows_explicitly(self):
        assert render_rows([]) == "(no rows)"

    def test_renders_columns_and_values(self):
        assert render_rows([{"a": 1, "b": 2}]) == "a=1; b=2"


class TestScorerHelpers:
    def test_strip_charts_removes_echarts_blocks(self):
        text = 'Revenue rose.\n\n```echarts\n{"series": []}\n```'
        assert _strip_charts(text) == "Revenue rose."

    def test_strip_charts_leaves_plain_prose(self):
        assert _strip_charts("Revenue rose.") == "Revenue rose."

    @pytest.mark.parametrize(
        "verdict,expected",
        [
            ({"score": True}, 1.0),
            ({"score": False}, 0.0),
            ({"score": 0.75}, 0.75),
            ({"score": None}, 0.0),
            ({}, 0.0),
        ],
    )
    def test_as_score_coerces(self, verdict, expected):
        assert _as_score(verdict) == expected

    def test_format_call_includes_arguments(self):
        # The judge cannot verify "in 2017" from result rows alone; the WHERE
        # clause lives in the tool arguments.
        rendered = _format_call(
            {"name": "sql_db_query", "args": {"query": "SELECT 1 WHERE year='2017'"}}
        )
        assert "sql_db_query(" in rendered
        assert "2017" in rendered
