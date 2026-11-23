"""Build the data for the static GitHub Pages demo.

Chunks the sample PDFs with the real ingestion code and, for a few suggested
questions, records the answers the real pipeline (hybrid retrieval + local LLM)
gives. The demo UI replays these; anything else falls back to retrieval only.

    python scripts/export_demo.py            # chunks only
    python scripts/export_demo.py --answers  # also asks Ollama (needs it running)
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion import chunk_pdf, hash_file  # noqa: E402

PDFS = ROOT / "data" / "pdfs"
OUT = ROOT / "frontend" / "src" / "demo" / "data.json"
SAMPLES = ROOT / "frontend" / "public" / "samples"

# (file name shown in the app, source pdf)
FILES = {
    "south-korea-itinerary.pdf": "South Korea 14-Day Travel Itinerary.pdf",
    "tokyo-itinerary.pdf": "Tokyo 14-Day Travel Itinerary.pdf",
    "philippines-itinerary.pdf": "Philippines 21-Day Travel Itinerary.pdf",
}
QUESTIONS = json.loads((Path(__file__).with_name("demo_questions.json")).read_text("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", action="store_true")
    ap.add_argument("--model", default="qwen2.5:1.5b-instruct")
    args = ap.parse_args()

    SAMPLES.mkdir(parents=True, exist_ok=True)
    docs = []
    for name, src in FILES.items():
        path = PDFS / src
        shutil.copy(path, SAMPLES / name)
        chunks = chunk_pdf(path, source=name)
        pages = max(c.metadata["page"] for c in chunks) + 1
        docs.append(
            {
                "name": name,
                "size": path.stat().st_size,
                "hash": hash_file(path),
                "pages": pages,
                "chunks": [{"page": c.metadata["page"] + 1, "text": " ".join(c.page_content.split())} for c in chunks],
            }
        )

    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    answers = old.get("answers", [])
    if args.answers:
        answers = generate_answers(args.model)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"docs": docs, "answers": answers}, indent=1, ensure_ascii=False), "utf-8")
    print(f"{len(docs)} documents, {sum(len(d['chunks']) for d in docs)} chunks, {len(answers)} cached answers")


def generate_answers(model):
    from langchain_community.llms import Ollama

    from qa import build_chain
    from retrieval import build_hybrid_retriever
    from store import open_store

    tmp = tempfile.mkdtemp()
    try:
        store = open_store(tmp, collection="demo")
        from ingestion import index_pdf

        for name, src in FILES.items():
            index_pdf(store, PDFS / src, content_hash=hash_file(PDFS / src), source=name)
        chain = build_chain(Ollama(model=model, temperature=0), build_hybrid_retriever(store, k=4))
        out = []
        for q in QUESTIONS:
            res = chain.invoke({"query": q})
            seen, sources = set(), []
            for d in res["source_documents"]:
                key = (d.metadata["source"], d.metadata["page"] + 1)
                if key not in seen:
                    seen.add(key)
                    sources.append(
                        {"document": key[0], "page": key[1], "snippet": " ".join(d.page_content.split())[:240]}
                    )
            print(f"Q: {q}\nA: {res['result']}\n   {[(s['document'], s['page']) for s in sources]}\n")
            out.append({"question": q, "answer": res["result"].strip(), "sources": sources})
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
