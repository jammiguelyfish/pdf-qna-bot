"""Evaluate the PDF Q&A bot against a hand-written question set.

Retrieval (default, no LLM needed): for every answerable question in
``eval/questions.json``, is the chunk containing the answer among the top-k
retrieved, and how high does it rank? Dense, BM25 and hybrid retrieval are
compared side by side.

Answers (``--answers``, needs Ollama): runs the real RetrievalQA chain and
checks each answer for the expected text, and that unanswerable questions are
refused instead of invented.

    python evaluate.py
    python evaluate.py --answers
    python evaluate.py --k 6 --out eval/results.md
"""
import argparse
import json
from pathlib import Path

QUESTIONS_FILE = Path(__file__).parent / "eval" / "questions.json"
REFUSAL = "i don't know based on the provided document"


def norm(text: str) -> str:
    """Lowercase and collapse whitespace so PDF line breaks don't matter."""
    return " ".join(text.lower().split())


def load_questions(path=QUESTIONS_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def first_hit_rank(docs, needle: str):
    """1-based rank of the first chunk containing ``needle``, or None."""
    needle = norm(needle)
    for rank, doc in enumerate(docs, 1):
        if needle in norm(doc.page_content):
            return rank
    return None


def retrieval_metrics(ranks: list, k: int) -> dict:
    """hit@k and mean reciprocal rank over the ranks of the answer chunk."""
    n = len(ranks)
    hits = [r for r in ranks if r is not None and r <= k]
    return {
        "n": n,
        "hits": len(hits),
        "hit_rate": len(hits) / n if n else 0.0,
        "mrr": sum(1 / r for r in hits) / n if n else 0.0,
    }


def answer_correct(answer: str, item: dict) -> bool:
    """Answerable: contains one expected string. Unanswerable: is a refusal."""
    text = norm(answer)
    if item.get("answerable", True):
        return any(norm(a) in text for a in item["answer_contains"])
    return REFUSAL in text


def build_retrievers(vectorstore, k: int) -> dict:
    from retrieval import build_bm25_retriever, build_hybrid_retriever

    return {
        "dense": vectorstore.as_retriever(search_kwargs={"k": k}),
        "bm25": build_bm25_retriever(vectorstore, k=k),
        "hybrid": build_hybrid_retriever(vectorstore, k=k),
    }


def evaluate_retrieval(retrievers: dict, questions: list[dict], k: int):
    answerable = [q for q in questions if q.get("answerable", True)]
    results, misses = {}, {}
    for name, retriever in retrievers.items():
        ranks = []
        for q in answerable:
            docs = retriever.get_relevant_documents(q["question"])
            ranks.append(first_hit_rank(docs, q["must_contain"]))
        results[name] = retrieval_metrics(ranks, k)
        misses[name] = [q["question"] for q, r in zip(answerable, ranks) if r is None]
    return results, misses


def evaluate_answers(chain, questions: list[dict]):
    rows = []
    for q in questions:
        out = chain.invoke({"query": q["question"]})
        rows.append((q, out["result"].strip(), answer_correct(out["result"], q)))
    return rows


def format_report(k, retrieval, misses, answers=None, model=None) -> str:
    lines = [f"### Retrieval (is the answer chunk in the top {k}?)", ""]
    lines += ["| Retriever | Hit rate | MRR |", "|---|---|---|"]
    for name, m in retrieval.items():
        lines.append(f"| {name} | {m['hits']}/{m['n']} ({m['hit_rate']:.0%}) | {m['mrr']:.2f} |")
    for name, missed in misses.items():
        if missed:
            lines += ["", f"Missed by **{name}**:"] + [f"- {q}" for q in missed]
    if answers:
        answerable = [a for a in answers if a[0].get("answerable", True)]
        unanswerable = [a for a in answers if not a[0].get("answerable", True)]
        lines += ["", f"### Answers (`{model}`, hybrid retriever)", ""]
        lines.append(f"- Answerable questions correct: {sum(a[2] for a in answerable)}/{len(answerable)}")
        lines.append(f"- Unanswerable questions refused: {sum(a[2] for a in unanswerable)}/{len(unanswerable)}")
        wrong = [a for a in answers if not a[2]]
        if wrong:
            lines += ["", "Wrong answers:"]
            lines += [f"- {q['question']} -> {text!r}" for q, text, _ in wrong]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Evaluate the PDF Q&A bot")
    parser.add_argument("--k", type=int, default=4, help="chunks retrieved per question")
    parser.add_argument("--answers", action="store_true", help="also grade LLM answers (needs Ollama)")
    parser.add_argument("--questions", default=str(QUESTIONS_FILE))
    parser.add_argument("--out", help="also write the report to this Markdown file")
    args = parser.parse_args()

    from qa import LLM_MODEL, build_chain, load_vectorstore

    questions = load_questions(args.questions)
    vectorstore = load_vectorstore()
    retrievers = build_retrievers(vectorstore, args.k)
    retrieval, misses = evaluate_retrieval(retrievers, questions, args.k)

    answers = None
    if args.answers:
        from langchain_community.llms import Ollama

        chain = build_chain(Ollama(model=LLM_MODEL, temperature=0), retrievers["hybrid"])
        answers = evaluate_answers(chain, questions)

    report = format_report(args.k, retrieval, misses, answers, LLM_MODEL)
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
