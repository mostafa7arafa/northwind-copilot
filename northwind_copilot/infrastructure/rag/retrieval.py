"""Build and load the FAISS index over the markdown knowledge base."""

from __future__ import annotations

import os
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from northwind_copilot.config import settings


def _load_docs(docs_dir: str) -> list[Document]:
    """Read markdown files and split them into paragraph-sized chunks.

    Args:
        docs_dir: Directory containing ``*.md`` knowledge documents.

    Returns:
        One :class:`~langchain_core.documents.Document` per non-empty paragraph,
        tagged with its source filename.
    """
    documents: list[Document] = []
    for md_file in Path(docs_dir).glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if chunk:
                documents.append(
                    Document(page_content=chunk, metadata={"source": md_file.name})
                )
    return documents


def load_or_build_index(docs_dir: str | None = None) -> FAISS:
    """Load the FAISS index from disk, or build and persist it.

    The index is rebuilt when the ``REINDEX`` environment variable is truthy or
    when no persisted index exists yet.

    Args:
        docs_dir: Override for the documents directory; defaults to the
            configured :attr:`Settings.docs_dir`.

    Returns:
        A ready-to-query FAISS vector store.

    Raises:
        ValueError: If no markdown files are found when a build is required.
    """
    docs_dir = docs_dir or settings.docs_dir
    embeddings = OpenAIEmbeddings(model=settings.embedding_model)
    should_reindex = os.getenv("REINDEX", "false").lower() == "true"

    if not should_reindex and os.path.exists(settings.faiss_path):
        return FAISS.load_local(
            settings.faiss_path, embeddings, allow_dangerous_deserialization=True
        )

    docs = _load_docs(docs_dir)
    if not docs:
        raise ValueError(f"No markdown files found in {docs_dir}")

    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(settings.faiss_path)
    return vectorstore
