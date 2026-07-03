"""Unit tests for the ``search_docs`` tool (index faked, no embeddings needed)."""

from __future__ import annotations

from langchain_core.documents import Document

from northwind_copilot.infra import docs_tool


class _FakeIndex:
    def __init__(self):
        self.calls = 0

    def similarity_search(self, query, k=4):
        self.calls += 1
        return [
            Document(
                page_content="AOV = revenue / orders", metadata={"source": "kpi.md"}
            ),
            Document(page_content="Summer runs Jun-Aug", metadata={"source": "cal.md"}),
        ]


def test_search_docs_formats_results(monkeypatch):
    fake = _FakeIndex()
    monkeypatch.setattr(docs_tool, "_index", None)
    monkeypatch.setattr(docs_tool, "load_or_build_index", lambda: fake)

    out = docs_tool.search_docs.func("what is AOV?")
    assert "[kpi.md]" in out
    assert "AOV = revenue / orders" in out
    assert "[cal.md]" in out


def test_index_is_cached(monkeypatch):
    fake = _FakeIndex()
    builds = {"n": 0}

    def _build():
        builds["n"] += 1
        return fake

    monkeypatch.setattr(docs_tool, "_index", None)
    monkeypatch.setattr(docs_tool, "load_or_build_index", _build)

    docs_tool._get_index()
    docs_tool._get_index()
    assert builds["n"] == 1  # built once, then cached
