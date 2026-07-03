"""The ``search_docs`` tool: semantic search over the knowledge base."""

from __future__ import annotations

from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool

from northwind_copilot.infra.rag import load_or_build_index

_index: FAISS | None = None


def _get_index() -> FAISS:
    """Return the process-wide FAISS index, building it on first use.

    Returns:
        The lazily-initialised vector store.
    """
    global _index
    if _index is None:
        _index = load_or_build_index()
    return _index


@tool
def search_docs(query: str) -> str:
    """Search the Northwind retail knowledge base for KPI definitions (AOV, margin),
    campaign dates (Summer, Winter), product categories, and return policies.
    Call this before writing SQL for any question about KPIs, campaigns, or policies.
    """
    results = _get_index().similarity_search(query, k=4)
    return "\n\n".join(f"[{r.metadata['source']}]\n{r.page_content}" for r in results)
