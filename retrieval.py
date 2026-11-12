"""Hybrid (dense + BM25) retrieval for the PDF Q&A bot.

Dense embeddings alone miss exact terms ("Busan") and differently spelled dates
("January 15" in the question vs "Jan 15" in the PDF). Fusing them with a BM25
keyword retriever fixes both, without changing how documents are chunked.
"""
import re

from langchain.retrievers import EnsembleRetriever
from langchain.schema import BaseRetriever, Document
from langchain_community.retrievers import BM25Retriever

_MONTHS = (
    "january february march april may june july "
    "august september october november december"
).split()


def normalize_months(text: str) -> str:
    """Lowercase and shorten full month names ('January' -> 'jan')."""
    text = text.lower()
    for month in _MONTHS:
        text = re.sub("(?<![a-z])" + month + "(?![a-z])", month[:3], text)
    return text


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize_months(text))


class _MonthNormalizedRetriever(BaseRetriever):
    """Normalizes month names in the query before delegating to ``base``."""

    base: BaseRetriever

    def _get_relevant_documents(self, query, *, run_manager=None):
        return self.base.get_relevant_documents(normalize_months(query))


class _TopKRetriever(BaseRetriever):
    """Keeps only the best ``k`` documents of ``base``."""

    base: BaseRetriever
    k: int

    def _get_relevant_documents(self, query, *, run_manager=None):
        return self.base.get_relevant_documents(query)[: self.k]


def build_hybrid_retriever(vectorstore, k: int = 4, candidates: int = 10) -> BaseRetriever:
    """Fuse dense and BM25 rankings (reciprocal rank fusion), return the top ``k``.

    Each retriever contributes ``candidates`` chunks so that a chunk ranked 5th
    by one of them can still win after fusion.
    """
    data = vectorstore.get(include=["documents", "metadatas"])
    docs = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(data["documents"], data["metadatas"])
    ]
    bm25 = BM25Retriever.from_documents(docs, k=candidates, preprocess_func=tokenize)
    dense = _MonthNormalizedRetriever(
        base=vectorstore.as_retriever(search_kwargs={"k": candidates})
    )
    fused = EnsembleRetriever(retrievers=[bm25, dense], weights=[0.5, 0.5])
    return _TopKRetriever(base=fused, k=k)
