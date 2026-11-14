import glob
import os

import pytest
from langchain.schema import Document

from evaluate import (
    answer_correct,
    first_hit_rank,
    load_questions,
    norm,
    retrieval_metrics,
)

ROOT = os.path.dirname(os.path.dirname(__file__))


def _docs(*texts):
    return [Document(page_content=t) for t in texts]


def test_first_hit_rank_ignores_case_and_line_breaks():
    docs = _docs("nothing here", "Busan (3\nnights) then Jeju")
    assert first_hit_rank(docs, "busan (3 nights)") == 2
    assert first_hit_rank(docs, "Seoul") is None


def test_retrieval_metrics_counts_hits_within_k_and_mrr():
    m = retrieval_metrics([1, 3, None, 5], k=4)
    assert (m["n"], m["hits"]) == (4, 2)  # rank 5 is outside the top 4
    assert m["hit_rate"] == 0.5
    assert m["mrr"] == pytest.approx((1 + 1 / 3) / 4)


def test_answer_correct_for_answerable_and_unanswerable_questions():
    item = {"answer_contains": ["Suica", "PASMO"]}
    assert answer_correct("Get a PASMO card.", item)
    assert not answer_correct("A bus pass.", item)
    refusal = {"answerable": False}
    assert answer_correct("I don't know based on the provided document.", refusal)
    assert not answer_correct("It is sunny in Paris.", refusal)


def test_question_file_is_well_formed():
    questions = load_questions()
    assert len({q["question"] for q in questions}) == len(questions)
    for q in questions:
        if q.get("answerable", True):
            assert q["must_contain"] and q["answer_contains"], q["question"]
    assert any(not q.get("answerable", True) for q in questions)


def test_every_expected_fact_really_is_in_the_sample_pdfs():
    pypdf = pytest.importorskip("pypdf")
    pdfs = glob.glob(os.path.join(ROOT, "data", "pdfs", "*.pdf"))
    assert pdfs, "sample PDFs are missing"
    text = norm(" ".join(p.extract_text() for f in pdfs for p in pypdf.PdfReader(f).pages))
    for q in load_questions():
        if q.get("answerable", True):
            assert norm(q["must_contain"]) in text, q["question"]
