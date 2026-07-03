"""Unit tests for the benchmark runner (agent faked; no LLM or network)."""

from __future__ import annotations

import json
import sys
import types

from langchain_core.messages import AIMessage

from northwind_copilot.eval import run_benchmark as rb


class TestLoadDataset:
    def test_parses_and_skips_blank_lines(self, tmp_path):
        path = tmp_path / "ds.jsonl"
        path.write_text(
            '{"id": "a", "question": "q1"}\n\n{"id": "b", "question": "q2"}\n',
            encoding="utf-8",
        )
        rows = rb.load_dataset(path)
        assert [r["id"] for r in rows] == ["a", "b"]


class TestExtractAnswer:
    def test_last_ai_message_with_content(self):
        msgs = [AIMessage(content="first"), AIMessage(content="second")]
        assert rb.extract_answer(msgs) == "second"

    def test_joins_content_blocks(self):
        msg = AIMessage(content=[{"text": "a"}, {"text": "b"}])
        assert rb.extract_answer([msg]) == "a b"

    def test_empty_when_no_ai_content(self):
        assert rb.extract_answer([AIMessage(content="")]) == ""


class TestModelsUsed:
    def test_distinct_in_order(self):
        msgs = [
            AIMessage(content="x", response_metadata={"model_name": "gemma"}),
            AIMessage(content="y", response_metadata={"model": "gpt-4.1-mini"}),
            AIMessage(content="z", response_metadata={"model_name": "gemma"}),
        ]
        assert rb.models_used(msgs) == ["gemma", "gpt-4.1-mini"]


class _FakeGraph:
    def __init__(self, answer="the count is 5", raise_exc=None):
        self._answer = answer
        self._raise = raise_exc

    def invoke(self, inp, config=None):
        if self._raise is not None:
            raise self._raise
        return {
            "messages": [
                AIMessage(
                    content=self._answer, response_metadata={"model_name": "gemma"}
                )
            ]
        }


class TestRunOne:
    def test_passing_numeric(self):
        record = {
            "id": "c",
            "question": "how many?",
            "grader": "numeric",
            "expected": 5,
        }
        res = rb.run_one(_FakeGraph(), record)
        assert res["passed"] is True
        assert res["models"] == ["gemma"]
        assert res["error"] is None

    def test_exception_is_reported_as_failure(self):
        record = {"id": "c", "question": "q", "grader": "numeric", "expected": 5}
        res = rb.run_one(_FakeGraph(raise_exc=RuntimeError("boom")), record)
        assert res["passed"] is False
        assert "boom" in res["error"]


def _inject_fake_graph(monkeypatch):
    fake_mod = types.ModuleType("northwind_copilot.query.graph")
    fake_mod.graph = _FakeGraph()
    monkeypatch.setitem(sys.modules, "northwind_copilot.query.graph", fake_mod)


class TestMain:
    def test_run_without_save(self, monkeypatch):
        _inject_fake_graph(monkeypatch)
        monkeypatch.setattr(
            rb, "load_dataset", lambda path: [{"id": "a", "question": "q"}]
        )
        monkeypatch.setattr(
            rb,
            "run_one",
            lambda graph, rec: {
                "id": rec["id"],
                "passed": True,
                "detail": "ok",
                "models": ["gemma"],
                "latency_s": 0.1,
                "answer": "5",
                "error": None,
            },
        )
        monkeypatch.setattr(sys, "argv", ["run_benchmark", "--no-save"])
        assert rb.main() == 0

    def test_run_saves_results(self, monkeypatch, tmp_path):
        _inject_fake_graph(monkeypatch)
        monkeypatch.setattr(
            rb, "load_dataset", lambda path: [{"id": "a", "question": "q"}]
        )
        monkeypatch.setattr(
            rb,
            "run_one",
            lambda graph, rec: {
                "id": rec["id"],
                "passed": False,
                "detail": "nope",
                "models": [],
                "latency_s": 0.2,
                "answer": "",
                "error": None,
            },
        )
        monkeypatch.setattr(rb, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(sys, "argv", ["run_benchmark"])
        rc = rb.main()
        assert rc == 2  # a failing question yields exit code 2
        latest = json.loads((tmp_path / "results" / "latest.json").read_text("utf-8"))
        assert latest["total"] == 1 and latest["passed"] == 0
