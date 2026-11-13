from langchain.schema import BaseRetriever, Document

from retrieval import build_hybrid_retriever, normalize_months, tokenize


def test_normalize_months_shortens_full_names_only():
    assert normalize_months("Where are we going on January 15?") == "where are we going on jan 15?"
    assert normalize_months("MARCH and Marching") == "mar and marching"  # whole words only


def test_tokenize_matches_pdf_and_question_spellings():
    assert "jan" in tokenize("Jan 15: Sagada") and "jan" in tokenize("January 15")
    assert tokenize("Day 3, Busan!") == ["day", "3", "busan"]


class _FakeDense(BaseRetriever):
    """Stands in for embeddings search: returns the wrong chunk first."""

    docs: list

    def _get_relevant_documents(self, query, *, run_manager=None):
        return self.docs


class _FakeStore:
    def __init__(self, docs):
        self._docs = docs

    def get(self, include=None):
        return {
            "documents": [d.page_content for d in self._docs],
            "metadatas": [d.metadata for d in self._docs],
        }

    def as_retriever(self, search_kwargs=None):
        # dense ranking puts the irrelevant chunks ahead of the right one
        return _FakeDense(docs=list(reversed(self._docs)))


def _store():
    return _FakeStore(
        [
            Document(page_content="Jan 15: Sagada to Baguio to Manila", metadata={"page": 0}),
            Document(page_content="Oct 20: East Coast Busan", metadata={"page": 1}),
            Document(page_content="Tokyo transit: get a Suica or PASMO card", metadata={"page": 2}),
            Document(page_content="Packing list and visa notes", metadata={"page": 3}),
        ]
    )


def test_hybrid_finds_a_date_written_differently_in_the_question():
    retriever = build_hybrid_retriever(_store(), k=2)
    pages = [d.metadata["page"] for d in retriever.get_relevant_documents("Where are we going on January 15?")]
    assert 0 in pages


def test_hybrid_returns_at_most_k_documents():
    retriever = build_hybrid_retriever(_store(), k=3)
    assert len(retriever.get_relevant_documents("Busan")) <= 3
