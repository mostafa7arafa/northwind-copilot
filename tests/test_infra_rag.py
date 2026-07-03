"""Unit tests for the FAISS index builder.

Embeddings and FAISS are faked so no OpenAI call or real index is created.
"""

from __future__ import annotations

import pytest

from northwind_copilot.infra import rag


class _FakeStore:
    def __init__(self, docs=None):
        self.docs = docs
        self.saved_to = None

    def save_local(self, path):
        self.saved_to = path


class _FakeFAISS:
    last_built = None

    @staticmethod
    def load_local(path, embeddings, allow_dangerous_deserialization=False):
        return _FakeStore(docs="loaded")

    @staticmethod
    def from_documents(docs, embeddings):
        store = _FakeStore(docs=docs)
        _FakeFAISS.last_built = store
        return store


@pytest.fixture(autouse=True)
def _patch_embeddings(monkeypatch):
    # OpenAIEmbeddings would need a real key; swap it for a no-op stub.
    monkeypatch.setattr(rag, "OpenAIEmbeddings", lambda **kwargs: object())
    monkeypatch.setattr(rag, "FAISS", _FakeFAISS)


class TestLoadDocs:
    def test_splits_paragraphs_and_tags_source(self, tmp_path):
        (tmp_path / "kpi.md").write_text(
            "First para.\n\n  \n\nSecond para.", encoding="utf-8"
        )
        docs = rag._load_docs(str(tmp_path))
        assert [d.page_content for d in docs] == ["First para.", "Second para."]
        assert all(d.metadata["source"] == "kpi.md" for d in docs)


class TestLoadOrBuildIndex:
    def test_loads_existing_index(self, monkeypatch):
        monkeypatch.delenv("REINDEX", raising=False)
        monkeypatch.setattr(rag.os.path, "exists", lambda p: True)
        store = rag.load_or_build_index(docs_dir="unused")
        assert store.docs == "loaded"

    def test_builds_and_persists_when_reindexing(self, monkeypatch, tmp_path):
        (tmp_path / "policy.md").write_text("A rule.", encoding="utf-8")
        monkeypatch.setenv("REINDEX", "true")
        store = rag.load_or_build_index(docs_dir=str(tmp_path))
        assert store is _FakeFAISS.last_built
        assert store.saved_to == rag.settings.faiss_path

    def test_raises_when_no_docs(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REINDEX", "true")
        with pytest.raises(ValueError, match="No markdown files"):
            rag.load_or_build_index(docs_dir=str(tmp_path))
