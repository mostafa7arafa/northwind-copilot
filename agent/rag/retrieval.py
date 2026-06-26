import os
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

FAISS_PATH = ".faiss_index"


def _load_docs(docs_dir: str) -> list[Document]:
    documents = []
    for md_file in Path(docs_dir).glob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if chunk:
                documents.append(
                    Document(page_content=chunk, metadata={"source": md_file.name})
                )
    return documents


def load_or_build_index(docs_dir: str = "docs") -> FAISS:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    should_reindex = os.getenv("REINDEX", "false").lower() == "true"

    if not should_reindex and os.path.exists(FAISS_PATH):
        return FAISS.load_local(
            FAISS_PATH, embeddings, allow_dangerous_deserialization=True
        )

    docs = _load_docs(docs_dir)
    if not docs:
        raise ValueError(f"No markdown files found in {docs_dir}")

    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(FAISS_PATH)
    return vectorstore
